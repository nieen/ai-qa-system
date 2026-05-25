"""
Milvus 向量数据库客户端
负责向量存储、混合检索（稠密+稀疏+BM25）
"""
import json
import logging
from typing import List, Optional, Dict, Any

from config.settings import settings
from app.core.protocols import VectorStore, KeywordStore, Document as DocModel, RetrievedChunk

logger = logging.getLogger(__name__)


class MilvusClient(VectorStore):
    """Milvus 向量数据库客户端"""
    
    # 注意: 实例由 Container 管理，不在此使用全局单例
    _is_initialized = False

    async def initialize(self):
        if self._is_initialized:
            return

        try:
            from pymilvus import (
                connections,
                Collection,
                CollectionSchema,
                FieldSchema,
                DataType,
                utility,
            )

            # 连接 Milvus
            connections.connect(
                alias=settings.MILVUS_COLLECTION_PREFIX.strip("_"),
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
            )
            logger.info(f"Milvus 连接成功: {settings.MILVUS_HOST}:{settings.MILVUS_PORT}")

            self._is_initialized = True
        except Exception as e:
            logger.warning(f"Milvus 连接失败: {e}")
            logger.warning("搜索功能将不可用")

    async def create_collection(self, collection_name: str):
        """
        创建集合
        Args:
            collection_name: 集合名称
        """
        if not self._is_initialized:
            return

        from pymilvus import (
            Collection,
            CollectionSchema,
            FieldSchema,
            DataType,
            utility,
        )

        full_name = f"{settings.MILVUS_COLLECTION_PREFIX}{collection_name}"

        if utility.has_collection(full_name):
            logger.info(f"集合已存在: {full_name}")
            return

        # 定义字段
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
            # 稀疏向量 (BGE-M3 输出)
            FieldSchema(name="sparse_embedding", dtype=DataType.SPARSE_FLOAT_VECTOR),
            # 元数据 (JSON 字符串存储)
            FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=2048),
        ]

        schema = CollectionSchema(
            fields,
            description=f"AI QA System - {collection_name}",
            enable_dynamic_field=True,
        )

        collection = Collection(name=full_name, schema=schema)

        # 创建索引
        # 稠密向量索引 (IVF_FLAT 平衡性能和准确率)
        collection.create_index(
            field_name="embedding",
            index_params={
                "metric_type": "IP",  # 内积 (与归一化向量结合 = 余弦相似度)
                "index_type": "IVF_FLAT",
                "params": {"nlist": 1024},
            },
        )

        # 稀疏向量索引
        collection.create_index(
            field_name="sparse_embedding",
            index_params={
                "metric_type": "IP",
                "index_type": "SPARSE_INVERTED_INDEX",
                "params": {"inverted_index_algo": "DAAT_MAXSCORE"},
            },
        )

        # 加载集合到内存
        collection.load()

        logger.info(f"集合创建完成: {full_name}")
        return collection

    async def insert(
        self,
        collection_name: str,
        documents: List[DocModel],
        embeddings: List[List[float]],
    ):
        """
        插入向量数据
        Args:
            collection_name: 集合名称
            documents: 文档块 (Document 对象)
            embeddings: 稠密向量
        """
        if not self._is_initialized or not documents:
            return

        from pymilvus import Collection

        full_name = f"{settings.MILVUS_COLLECTION_PREFIX}{collection_name}"
        collection = Collection(name=full_name)

        # 准备插入数据
        insert_data = []
        for i, doc in enumerate(documents):
            insert_data.append({
                "chunk_id": doc.chunk_id,
                "document_id": doc.document_id,
                "kb_id": doc.kb_id,
                "chunk_index": doc.chunk_index,
                "content": doc.content,
                "embedding": embeddings[i] if i < len(embeddings) else [],
                "metadata": json.dumps(doc.metadata, ensure_ascii=False),
            })

        result = collection.insert(insert_data)
        collection.flush()

        logger.info(f"写入 {len(documents)} 个向量到 {full_name}")
        return result

    async def similarity_search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 30,
        kb_id: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        """
        纯向量相似度搜索 (不依赖关键词索引)
        Args:
            collection_name: 集合名称
            query_vector: 查询向量
            top_k: 返回数量
            kb_id: 知识库 ID 过滤
        Returns:
            RetrievedChunk 列表
        """
        if not self._is_initialized:
            return []

        from pymilvus import Collection, AnnSearchRequest, RRFRanker

        full_name = f"{settings.MILVUS_COLLECTION_PREFIX}{collection_name}"
        collection = Collection(name=full_name)
        collection.load()

        expr = None
        if kb_id:
            expr = f'kb_id == "{kb_id}"'

        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "IP", "params": {"nprobe": 16}},
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id", "document_id", "kb_id", "content", "metadata"],
        )

        parsed: List[RetrievedChunk] = []
        if results and len(results) > 0:
            for hit in results[0]:
                meta = _parse_metadata(hit.entity.get("metadata"))
                parsed.append(RetrievedChunk(
                    chunk_id=hit.entity.get("chunk_id") or "",
                    document_id=hit.entity.get("document_id") or "",
                    kb_id=hit.entity.get("kb_id") or "",
                    content=hit.entity.get("content") or "",
                    score=hit.score,
                    metadata=meta,
                    source_file=meta.get("source_file", ""),
                    retrieval_type="vector",
                ))

        logger.info(f"向量检索返回 {len(parsed)} 条结果")
        return parsed

    async def delete_by_document(self, collection_name: str, document_id: str):
        """删除文档的所有向量"""
        if not self._is_initialized:
            return

        from pymilvus import Collection

        full_name = f"{settings.MILVUS_COLLECTION_PREFIX}{collection_name}"
        collection = Collection(name=full_name)
        collection.delete(f'document_id == "{document_id}"')
        logger.info(f"已删除文档 {document_id} 的向量")

    async def delete_collection(self, collection_name: str):
        """删除整个集合"""
        if not self._is_initialized:
            return

        from pymilvus import utility

        full_name = f"{settings.MILVUS_COLLECTION_PREFIX}{collection_name}"
        if utility.has_collection(full_name):
            utility.drop_collection(full_name)
            logger.info(f"已删除集合: {full_name}")

    async def close(self):
        """关闭连接 (由 Container 管理)"""
        from pymilvus import connections
        try:
            connections.disconnect(settings.MILVUS_COLLECTION_PREFIX.strip("_"))
            logger.info("Milvus 连接已关闭")
        except Exception as e:
            logger.debug(f"Milvus 关闭 (可忽略): {e}")


def _parse_metadata(raw) -> Dict[str, Any]:
    """解析 metadata 字段为 dict"""
    import json
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


class MilvusKeywordStore(KeywordStore):
    """
    Milvus 关键词检索实现 (利用 Milvus 内置 BM25)

    实现了 KeywordStore 接口，不依赖向量库是否支持混合检索。
    PGVector 用户可替换为 PGFTSStore (PostgreSQL 全文检索)。
    """

    _is_initialized = False

    async def initialize(self):
        self._is_initialized = True

    async def index_document(self, collection_name: str, document: Document):
        """Milvus 在 insert 时自动索引文本，无需单独操作"""
        pass

    async def keyword_search(
        self,
        collection_name: str,
        query_text: str,
        top_k: int = 30,
        kb_id: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        if not self._is_initialized:
            return []

        from pymilvus import Collection, AnnSearchRequest, RRFRanker

        full_name = f"{settings.MILVUS_COLLECTION_PREFIX}{collection_name}"
        collection = Collection(name=full_name)
        collection.load()

        # 使用 sparse 向量字段做 BM25 检索
        bm25_req = AnnSearchRequest(
            data=[query_text],  # Milvus 自动分词做 BM25
            anns_field="sparse_embedding",
            param={"metric_type": "IP"},
            limit=top_k,
            expr=f'kb_id == "{kb_id}"' if kb_id else None,
        )

        results = collection.hybrid_search(
            reqs=[bm25_req],
            rerank=RRFRanker(),
            limit=top_k,
            output_fields=["chunk_id", "document_id", "kb_id", "content", "metadata"],
        )

        parsed: List[RetrievedChunk] = []
        if results and len(results) > 0:
            for hit in results[0]:
                meta = _parse_metadata(hit.entity.get("metadata"))
                parsed.append(RetrievedChunk(
                    chunk_id=hit.entity.get("chunk_id") or "",
                    document_id=hit.entity.get("document_id") or "",
                    kb_id=hit.entity.get("kb_id") or "",
                    content=hit.entity.get("content") or "",
                    score=hit.score,
                    metadata=meta,
                    source_file=meta.get("source_file", ""),
                    retrieval_type="keyword",
                ))
        return parsed

    async def delete_by_document(self, collection_name: str, document_id: str):
        from pymilvus import Collection
        full_name = f"{settings.MILVUS_COLLECTION_PREFIX}{collection_name}"
        Collection(name=full_name).delete(f'document_id == "{document_id}"')

    async def delete_collection(self, collection_name: str):
        from pymilvus import utility
        full_name = f"{settings.MILVUS_COLLECTION_PREFIX}{collection_name}"
        if utility.has_collection(full_name):
            utility.drop_collection(full_name)

    async def close(self):
        pass


# 全局单例
milvus_client = MilvusClient()
