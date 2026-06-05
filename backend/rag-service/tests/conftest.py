"""
pytest 共享配置和 Fixtures

覆盖模式说明:
  - 单元测试: 使用 fake 或 mock 对象，不依赖外部服务
  - 集成测试: 需要 Redis/Milvus/PostgreSQL (通过 @pytest.mark.integration 标记)

测试策略:
  - 所有 AI 模型 (Embedding/Reranker/LLM) 都使用 unittest.mock
  - 事件总线使用 fakeredis (纯 Python Redis 模拟)
  - API 使用 httpx.AsyncClient 模拟 FastAPI 调用
"""
import asyncio
import sys
from pathlib import Path
from typing import AsyncGenerator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# 确保项目根目录在 sys.path 中
_proj_root = str(Path(__file__).resolve().parent.parent)
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from app.core.protocols import (
    VectorStore, KeywordStore, EmbeddingModel, Reranker,
    RetrievedChunk, Document, LLMResponse,
)


# ==================== Mock 服务实现 ====================


class MockVectorStore(VectorStore):
    """Mock 向量存储 — 返回固定检索结果"""

    def __init__(self):
        self.collections = set()
        self.documents: dict[str, list[dict]] = {}  # kb_id -> [chunk_data]
        self._initialized = False

    async def initialize(self):
        self._initialized = True

    async def create_collection(self, collection_name: str):
        self.collections.add(collection_name)
        if collection_name not in self.documents:
            self.documents[collection_name] = []

    async def insert(self, collection_name: str, documents: List[Document],
                     embeddings: List[List[float]]):
        if collection_name not in self.documents:
            self.documents[collection_name] = []
        for doc in documents:
            self.documents[collection_name].append({
                "chunk_id": doc.chunk_id,
                "document_id": doc.document_id,
                "content": doc.content,
                "kb_id": doc.kb_id,
            })

    async def similarity_search(self, collection_name: str, query_vector: List[float],
                                top_k: int = 30, kb_id: Optional[str] = None) -> List[RetrievedChunk]:
        docs = self.documents.get(collection_name, [])
        results = []
        for i, doc in enumerate(docs[:top_k]):
            results.append(RetrievedChunk(
                chunk_id=doc["chunk_id"],
                document_id=doc["document_id"],
                kb_id=doc["kb_id"],
                content=doc["content"],
                score=1.0 - (i * 0.01),
                retrieval_type="vector",
            ))
        return results

    async def delete_by_document(self, collection_name: str, document_id: str):
        if collection_name in self.documents:
            self.documents[collection_name] = [
                d for d in self.documents[collection_name]
                if d["document_id"] != document_id
            ]

    async def delete_collection(self, collection_name: str):
        self.collections.discard(collection_name)
        self.documents.pop(collection_name, None)

    async def close(self):
        pass


class MockKeywordStore(KeywordStore):
    """Mock 关键词存储 — 简单文本匹配"""

    def __init__(self):
        self.documents: dict[str, list[dict]] = {}

    async def initialize(self):
        pass

    async def index_document(self, collection_name: str, document: Document):
        pass

    async def keyword_search(self, collection_name: str, query_text: str,
                             top_k: int = 30, kb_id: Optional[str] = None) -> List[RetrievedChunk]:
        docs = self.documents.get(collection_name, [])
        query_lower = query_text.lower()
        results = []
        for doc in docs:
            if query_lower in doc["content"].lower():
                results.append(RetrievedChunk(
                    chunk_id=doc["chunk_id"],
                    document_id=doc["document_id"],
                    kb_id=doc["kb_id"],
                    content=doc["content"],
                    score=0.9,
                    retrieval_type="keyword",
                ))
        return results[:top_k]

    async def delete_by_document(self, collection_name: str, document_id: str):
        pass

    async def delete_collection(self, collection_name: str):
        pass

    async def close(self):
        pass


class MockEmbeddingModel(EmbeddingModel):
    """Mock 嵌入模型 — 返回固定维度向量"""

    def __init__(self, dim: int = 1024):
        self._dim = dim
        self._initialized = False

    async def initialize(self):
        self._initialized = True

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        import numpy as np
        return np.random.randn(len(texts), self._dim).tolist()

    async def embed_query(self, text: str) -> List[float]:
        import numpy as np
        return np.random.randn(self._dim).tolist()

    @property
    def dimension(self) -> int:
        return self._dim


class MockReranker(Reranker):
    """Mock 重排序 — 保持原序并打上 rerank_score"""

    async def initialize(self):
        pass

    async def rerank(self, query: str, documents: List[RetrievedChunk],
                     top_k: int = 5) -> List[RetrievedChunk]:
        for i, doc in enumerate(documents[:top_k]):
            doc.rerank_score = 1.0 - (i * 0.1)
        return documents[:top_k]


class MockLLMProvider:
    """Mock LLM 供应商 — 返回固定文本流"""

    def __init__(self, model_name: str = "mock-model", tokens: List[str] = None):
        self._model_name = model_name
        self._tokens = tokens or ["这是", "一条", "模拟", "回复", "。"]
        self._call_count = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    async def chat_stream(self, messages, temperature=0.3, max_tokens=8192):
        for token in self._tokens:
            yield token
            await asyncio.sleep(0)

    async def chat(self, messages, temperature=0.3, max_tokens=8192) -> LLMResponse:
        content = "".join(self._tokens)
        self._call_count += 1
        return LLMResponse(
            content=content,
            tokens_used=len(self._tokens),
            model_name=self._model_name,
        )

    async def check_health(self) -> bool:
        return True


# ==================== Fixtures ====================


@pytest.fixture
def mock_vector_store() -> MockVectorStore:
    return MockVectorStore()


@pytest.fixture
def mock_keyword_store() -> MockKeywordStore:
    return MockKeywordStore()


@pytest.fixture
def mock_embedding_model() -> MockEmbeddingModel:
    return MockEmbeddingModel(dim=1024)


@pytest.fixture
def mock_reranker() -> MockReranker:
    return MockReranker()


@pytest.fixture
def mock_llm_provider() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture
def mock_llm_router(mock_llm_provider):
    """创建 Mock LLMRouter"""
    with patch("app.core.llm_router.LLMRouter") as MockRouter:
        router = MockRouter.return_value
        router.primary = mock_llm_provider
        router.fallback = None
        router.current_model = "mock-model"
        router.is_fallback_mode = False
        router.total_fallbacks = 0
        router.check_health = AsyncMock(return_value={"status": "ok", "primary": True})
        router.chat_stream = mock_llm_provider.chat_stream
        router.reset = AsyncMock()
        router.close = AsyncMock()
        yield router


@pytest.fixture
def sample_chunks() -> List[RetrievedChunk]:
    """样本检索结果"""
    return [
        RetrievedChunk(
            chunk_id="chunk-1", document_id="doc-1", kb_id="kb-default",
            content="Redis Streams 是 Redis 5.0 引入的持久化消息队列。",
            score=0.95, retrieval_type="vector",
            source_file="redis-guide.md",
        ),
        RetrievedChunk(
            chunk_id="chunk-2", document_id="doc-1", kb_id="kb-default",
            content="消费者组允许多个消费者共同消费同一条消息。",
            score=0.88, retrieval_type="keyword",
            source_file="redis-guide.md",
        ),
        RetrievedChunk(
            chunk_id="chunk-3", document_id="doc-2", kb_id="kb-default",
            content="Milvus 是一款高性能向量数据库。",
            score=0.72, retrieval_type="vector",
            source_file="milvus-intro.md",
        ),
    ]


@pytest.fixture
def sample_document() -> Document:
    """样本文档块"""
    return Document(
        chunk_id="test-chunk",
        document_id="test-doc",
        kb_id="test-kb",
        chunk_index=0,
        content="这是一条测试文档内容。",
        metadata={"source_file": "test.txt", "file_type": "txt"},
    )
