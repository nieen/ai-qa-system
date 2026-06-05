"""
重排序服务 (BGE-Reranker)
对检索结果进行精排，提升最终答案质量

注意事项:
  - Transformers 推理是同步 GPU 操作，会阻塞事件循环
  - rerank 方法通过 run_in_executor 将 GPU 推理移出事件循环
  - 多副本部署: 每个副本独立加载模型，通过进程隔离避免显存竞争
"""
import asyncio
import logging
from typing import List
from concurrent.futures import ThreadPoolExecutor

from config.settings import settings
from app.core.protocols import Reranker, RetrievedChunk

logger = logging.getLogger(__name__)

# 全局线程池执行器
_reranker_executor = None


def _get_executor():
    global _reranker_executor
    if _reranker_executor is None:
        _reranker_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="reranker",
        )
    return _reranker_executor


class RerankerService(Reranker):
    """重排序服务"""

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._is_initialized = False

    async def initialize(self) -> None:
        if self._is_initialized:
            return

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            logger.info(f"加载重排序模型: {settings.RERANKER_MODEL}")

            # 模型加载在后台线程执行
            loop = asyncio.get_event_loop()
            self._tokenizer = await loop.run_in_executor(
                _get_executor(),
                lambda: AutoTokenizer.from_pretrained(
                    settings.RERANKER_MODEL, trust_remote_code=True
                ),
            )
            self._model = await loop.run_in_executor(
                _get_executor(),
                lambda: AutoModelForSequenceClassification.from_pretrained(
                    settings.RERANKER_MODEL,
                    trust_remote_code=True,
                    device_map=settings.RERANKER_DEVICE,
                ),
            )
            self._model.eval()
            self._is_initialized = True
            logger.info(f"重排序模型加载完成, 设备: {settings.RERANKER_DEVICE}")
        except Exception as e:
            logger.warning(f"重排序模型加载失败: {e}")
            self._is_initialized = False

    async def rerank(
        self,
        query: str,
        documents: List[RetrievedChunk],
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        """
        对检索结果进行重排序

        将同步的 Transformers 推理移出事件循环，
        避免在 GPU 推理时阻塞 SSE 流式响应。
        """
        if not documents:
            return []

        if not self._is_initialized:
            logger.warning("重排序模型不可用, 使用原始顺序")
            return documents[:top_k]

        try:
            import torch

            # 构建 query-document 对
            pairs = [[query, doc.content] for doc in documents]

            def _infer():
                inputs = self._tokenizer(
                    pairs,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                    max_length=512,
                )
                inputs = {k: v.to(self._model.device) for k, v in inputs.items()}
                with torch.no_grad():
                    return self._model(**inputs).logits.squeeze(-1)

            loop = asyncio.get_event_loop()
            scores = await loop.run_in_executor(_get_executor(), _infer)

            # 排序并保留 scores
            scored_docs = list(zip(documents, scores.tolist()))
            scored_docs.sort(key=lambda x: x[1], reverse=True)

            reranked = []
            for doc, score in scored_docs[:top_k]:
                doc.rerank_score = score
                reranked.append(doc)

            logger.info(f"重排序完成: {len(documents)} -> {len(reranked)}")
            return reranked

        except Exception as e:
            logger.error(f"重排序失败: {e}")
            return documents[:top_k]


# 全局单例
reranker_service = RerankerService()
