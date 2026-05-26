"""
核心抽象接口层
所有外部服务（向量库、关键词库、LLM、嵌入、重排序）都通过此接口定义，
使实现可替换、可测试、可 mock。

设计原则:
  - VectorStore: 纯向量相似度搜索 (所有向量库都支持)
  - KeywordStore: 纯关键词/全文检索 (独立于向量库)
  - Pipeline 层将两路结果做 RRF 融合，不依赖单个数据库的混合检索能力
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, AsyncIterator, List, Optional, Dict, Any, Protocol


# ==================== 数据模型 ====================


@dataclass
class Document:
    """文档块"""
    content: str
    chunk_id: str = ""
    document_id: str = ""
    kb_id: str = ""
    chunk_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    """检索结果"""
    content: str
    score: float
    rerank_score: float = 0.0
    chunk_id: str = ""
    document_id: str = ""
    kb_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_file: str = ""
    retrieval_type: str = "vector"  # vector | keyword


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    tokens_used: int = 0
    model_name: str = ""
    latency_ms: int = 0


@dataclass
class PipelineEvent:
    """Pipeline 执行事件（用于监控/日志/钩子）"""
    type: str
    data: Dict[str, Any] = field(default_factory=dict)


# ==================== RRF 融合工具 ====================


def rrf_merge(
    vector_results: List[RetrievedChunk],
    keyword_results: List[RetrievedChunk],
    k: int = 60,
    top_k: int = 30,
) -> List[RetrievedChunk]:
    """
    Reciprocal Rank Fusion (RRF) 融合两路检索结果

    不依赖任何数据库的内置能力，纯算法实现，适用于任何向量库+关键词库组合。

    Args:
        vector_results: 向量检索结果 (已按 score 降序)
        keyword_results: 关键词检索结果 (已按 score 降序)
        k: RRF 常数 (通常 60)
        top_k: 最终返回数量
    Returns:
        融合排序后的结果
    """
    # 计算每篇文档的 RRF 分数
    rrf_scores: Dict[str, Dict[str, Any]] = {}

    for rank, doc in enumerate(vector_results):
        key = doc.chunk_id or doc.content[:100]
        rrf_scores[key] = {
            "chunk": doc,
            "score": 1.0 / (k + rank + 1),
        }

    for rank, doc in enumerate(keyword_results):
        key = doc.chunk_id or doc.content[:100]
        if key in rrf_scores:
            rrf_scores[key]["score"] += 1.0 / (k + rank + 1)
        else:
            rrf_scores[key] = {
                "chunk": doc,
                "score": 1.0 / (k + rank + 1),
            }

    # 按 RRF 分数降序
    sorted_items = sorted(rrf_scores.values(), key=lambda x: x["score"], reverse=True)

    # 将 RRF 分数写回 chunk
    for item in sorted_items[:top_k]:
        item["chunk"].score = item["score"]

    return [item["chunk"] for item in sorted_items[:top_k]]


# ==================== 接口定义 ====================


class VectorStore(ABC):
    """向量数据库抽象接口 — 只做向量相似度搜索"""

    @abstractmethod
    async def initialize(self): ...

    @abstractmethod
    async def create_collection(self, collection_name: str): ...

    @abstractmethod
    async def insert(
        self,
        collection_name: str,
        documents: List[Document],
        embeddings: List[List[float]],
    ): ...

    @abstractmethod
    async def similarity_search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 30,
        kb_id: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        """
        纯向量相似度搜索
        所有向量数据库都支持此操作 (Milvus, PGVector, Qdrant, Chroma...)
        """
        ...

    @abstractmethod
    async def delete_by_document(self, collection_name: str, document_id: str): ...

    @abstractmethod
    async def delete_collection(self, collection_name: str): ...

    @abstractmethod
    async def close(self): ...


class KeywordStore(ABC):
    """关键词/全文检索抽象接口 — 独立于向量库"""

    @abstractmethod
    async def initialize(self): ...

    @abstractmethod
    async def index_document(self, collection_name: str, document: Document):
        """索引文档供关键词检索"""
        ...

    @abstractmethod
    async def keyword_search(
        self,
        collection_name: str,
        query_text: str,
        top_k: int = 30,
        kb_id: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        """
        纯关键词/全文检索
        实现方式可以是: PostgreSQL FTS、Elasticsearch、Whoosh、内存 BM25...
        不依赖向量库是否支持关键词检索。
        """
        ...

    @abstractmethod
    async def delete_by_document(self, collection_name: str, document_id: str): ...

    @abstractmethod
    async def delete_collection(self, collection_name: str): ...

    @abstractmethod
    async def close(self): ...


class EmbeddingModel(ABC):
    """嵌入模型抽象接口"""

    @abstractmethod
    async def initialize(self): ...

    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量文档向量化"""
        ...

    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        """单条查询向量化"""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """向量维度"""
        ...


class Reranker(ABC):
    """重排序模型抽象接口"""

    @abstractmethod
    async def initialize(self): ...

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: List[RetrievedChunk],
        top_k: int = 5,
    ) -> List[RetrievedChunk]: ...


class LLMProvider(ABC):
    """大语言模型供应商抽象接口"""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """模型标识名"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> AsyncGenerator[str, None]:
        """流式对话，每次 yield 一个 token"""
        ...

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        """非流式对话，返回完整响应"""
        ...

    @abstractmethod
    async def check_health(self) -> bool:
        """健康检查"""
        ...


# ==================== Pipeline 相关 ====================


class PipelineHook(Protocol):
    """Pipeline 钩子函数类型"""
    async def __call__(self, event: PipelineEvent) -> None: ...


class QueryPipeline(ABC):
    """查询 Pipeline 抽象接口
    Phase 1: NaiveRAGPipeline (retrieve → rerank → generate)
    Phase 2: AgenticRAGPipeline (plan → retrieve → reflect → repeat → generate)
    """

    @abstractmethod
    async def execute(
        self,
        question: str,
        kb_id: str,
        conversation_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncIterator[PipelineEvent]:
        """
        执行查询 Pipeline
        Yields:
            PipelineEvent 事件流 (token, metadata, done, error)
        """
        ...

    @abstractmethod
    def register_hook(self, hook: PipelineHook): ...

    @property
    @abstractmethod
    def pipeline_name(self) -> str: ...
