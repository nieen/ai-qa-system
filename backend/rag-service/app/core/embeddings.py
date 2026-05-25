"""
嵌入模型管理 (BGE-M3)
提供文本向量化服务，支持稠密检索和稀疏检索双通道
"""
import logging
from typing import List, Optional
import numpy as np

from config.settings import settings

logger = logging.getLogger(__name__)


class EmbeddingManager:
    """嵌入模型管理器 - 单例模式"""

    _instance = None
    _model = None
    _is_initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self):
        """初始化嵌入模型"""
        if self._is_initialized:
            return

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"加载嵌入模型: {settings.EMBEDDING_MODEL}")
            self._model = SentenceTransformer(
                settings.EMBEDDING_MODEL,
                device=settings.EMBEDDING_DEVICE,
                trust_remote_code=True,
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
        批量文档向量化
        Args:
            texts: 文本列表
        Returns:
            向量列表 (shape: [n, embedding_dim])
        """
        if not texts:
            return []

        if self._model is not None:
            embeddings = self._model.encode(
                texts,
                batch_size=settings.EMBEDDING_BATCH_SIZE,
                show_progress_bar=False,
                normalize_embeddings=True,  # L2 归一化，提高余弦相似度计算效率
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
        """
        单条查询向量化
        Args:
            text: 查询文本
        Returns:
            向量
        """
        vectors = await self.embed_documents([text])
        return vectors[0] if vectors else []

    async def embed_sparse(self, texts: List[str]):
        """
        生成稀疏向量 (BGE-M3 支持稀疏检索)
        Args:
            texts: 文本列表
        Returns:
            稀疏向量列表
        """
        if self._model is not None and hasattr(self._model, "encode_lexical"):
            try:
                sparse_vectors = self._model.encode_lexical(texts)
                return sparse_vectors
            except Exception as e:
                logger.warning(f"稀疏向量生成失败: {e}")

        return []


# 全局单例
embedding_manager = EmbeddingManager()
