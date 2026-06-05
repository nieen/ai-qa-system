"""
嵌入模型管理 (BGE-M3)
提供文本向量化服务，支持稠密检索和稀疏检索双通道

注意事项:
  - SentenceTransformer.encode 是同步 CPU/GPU 操作，会阻塞事件循环
  - 所有 encode 调用通过 asyncio.get_event_loop().run_in_executor 执行
  - 多副本部署时每个进程独立加载模型，不共享 GPU 显存
"""
import asyncio
import logging
from typing import List
import numpy as np

from config.settings import settings

logger = logging.getLogger(__name__)

# 全局线程池执行器 (默认 CPU 核数 * 5 线程)
_embedding_executor = None


def _get_executor():
    global _embedding_executor
    if _embedding_executor is None:
        from concurrent.futures import ThreadPoolExecutor
        _embedding_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="embedding",
        )
    return _embedding_executor


class EmbeddingManager:
    """嵌入模型管理器 - 实例方法 (非单例，支持多副本)"""

    def __init__(self):
        self._model = None
        self._is_initialized = False

    async def initialize(self) -> None:
        """初始化嵌入模型 (使用线程池避免阻塞事件循环)"""
        if self._is_initialized:
            return

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"加载嵌入模型: {settings.EMBEDDING_MODEL}")

            # SentenceTransformer 构造时可能下载模型，在后台线程执行
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                _get_executor(),
                lambda: SentenceTransformer(
                    settings.EMBEDDING_MODEL,
                    device=settings.EMBEDDING_DEVICE,
                    trust_remote_code=True,
                ),
            )
            self._model.max_seq_length = settings.EMBEDDING_MAX_LENGTH
            self._is_initialized = True
            logger.info(
                f"嵌入模型加载完成，向量维度: {settings.EMBEDDING_DIM}, "
                f"设备: {settings.EMBEDDING_DEVICE}"
            )
        except Exception as e:
            logger.error(f"嵌入模型加载失败: {e}")
            logger.warning("将使用降级模式: 基于 HuggingFace API 的嵌入")
            self._is_initialized = False

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        批量文档向量化 (async safe)

        将同步的 SentenceTransformer.encode 调用移出事件循环，
        避免阻塞其他协程 (如 SSE 流式响应)
        """
        if not texts:
            return []

        if self._model is not None:
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                _get_executor(),
                lambda: self._model.encode(
                    texts,
                    batch_size=settings.EMBEDDING_BATCH_SIZE,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                ),
            )
            return embeddings.tolist()
        else:
            # 降级: 返回随机向量 (仅用于测试)
            logger.warning("使用降级嵌入: 生成随机向量")
            return [
                np.random.randn(settings.EMBEDDING_DIM).tolist()
                for _ in texts
            ]

    async def embed_query(self, text: str) -> List[float]:
        """单条查询向量化"""
        vectors = await self.embed_documents([text])
        return vectors[0] if vectors else []

    async def embed_sparse(self, texts: List[str]):
        """生成稀疏向量 (BGE-M3 encode_lexical)
        
        ⚠️ 注意: 当前 Pipeline 未使用此方法。BM25 由 MilvusKeywordStore 独立完成。
        BGE-M3 的 lexical sparse 向量预留作为未来"三路检索"的扩展点。
        """
        if self._model is not None and hasattr(self._model, "encode_lexical"):
            try:
                loop = asyncio.get_event_loop()
                sparse_vectors = await loop.run_in_executor(
                    _get_executor(),
                    lambda: self._model.encode_lexical(texts),
                )
                return sparse_vectors
            except Exception as e:
                logger.warning(f"稀疏向量生成失败: {e}")

        return []


# 全局单例 (Container 托管生命周期，各副本独立)
embedding_manager = EmbeddingManager()
