"""
重排序服务 (BGE-Reranker)
对检索结果进行精排，提升最终答案质量
"""
import logging
from typing import List

from config.settings import settings
from app.core.protocols import Reranker, RetrievedChunk

logger = logging.getLogger(__name__)


class RerankerService(Reranker):
    """重排序服务"""
    
    # 实例由 Container 管理
    _model = None
    _is_initialized = False

    async def initialize(self) -> None:
        if self._is_initialized:
            return

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            logger.info(f"加载重排序模型: {settings.RERANKER_MODEL}")
            self._tokenizer = AutoTokenizer.from_pretrained(
                settings.RERANKER_MODEL, trust_remote_code=True
            )
            self._model = AutoModelForSequenceClassification.from_pretrained(
                settings.RERANKER_MODEL,
                trust_remote_code=True,
                device_map=settings.RERANKER_DEVICE,
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
        Args:
            query: 查询文本
            documents: 检索结果列表 (RetrievedChunk)
            top_k: 返回数量
        Returns:
            排序后的结果 (RetrievedChunk)
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

            # Tokenize
            inputs = self._tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512,
            )
            inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

            # 推理
            with torch.no_grad():
                scores = self._model(**inputs).logits.squeeze(-1)

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
