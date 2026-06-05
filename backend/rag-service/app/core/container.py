"""
依赖注入容器
组装所有服务实例，管理生命周期

多副本部署安全:
  - 每个进程创建独立的 Container 实例
  - 所有服务使用实例变量而非类变量
  - Container 实例由 lifespan 管理，不在模块层面创建
"""
import logging
from typing import Optional

from config.settings import settings
from app.core.protocols import (
    VectorStore, KeywordStore, EmbeddingModel, Reranker, QueryPipeline, LLMProvider,
)
from app.core.llm_router import LLMRouter
from app.core.cache import conversation_cache
from app.core.event_bus import event_bus
from app.core.pipeline import NaiveRAGPipeline
from app.retrieval.milvus_client import MilvusClient, MilvusKeywordStore
from app.core.embeddings import EmbeddingManager
from app.retrieval.reranker import RerankerService
from app.llm.providers import VLLMProvider, DeepSeekAPIProvider, OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class Container:
    """依赖注入容器，管理所有服务实例

    非单例: 每个进程 (API / Worker) 创建自己的容器
    """

    def __init__(self) -> None:
        self._initialized = False

        # 服务实例 (懒加载，实例变量保证每进程独立)
        self._vector_store: Optional[VectorStore] = None
        self._keyword_store: Optional[KeywordStore] = None
        self._embedding_model: Optional[EmbeddingModel] = None
        self._reranker: Optional[Reranker] = None
        self._llm_router: Optional[LLMRouter] = None
        self._pipeline: Optional[QueryPipeline] = None
        self._milvus_client: Optional[MilvusClient] = None
        self._keyword_client: Optional[MilvusKeywordStore] = None

    # ========== 工厂方法 ==========

    def get_vector_store(self) -> VectorStore:
        if self._vector_store is None:
            self._milvus_client = MilvusClient()
            self._vector_store = self._milvus_client
        return self._vector_store

    def get_embedding_model(self) -> EmbeddingModel:
        if self._embedding_model is None:
            self._embedding_model = EmbeddingManager()
        return self._embedding_model

    def get_reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = RerankerService()
        return self._reranker

    def get_keyword_store(self) -> KeywordStore:
        if self._keyword_store is None:
            store_type = settings.KEYWORD_STORE_TYPE
            if store_type == "milvus":
                self._keyword_client = MilvusKeywordStore()
                self._keyword_store = self._keyword_client
            elif store_type == "pgvector":
                raise NotImplementedError("PostgreSQL FTS 关键词检索尚未实现")
            elif store_type == "simple":
                raise NotImplementedError("Simple BM25 关键词检索尚未实现")
            else:
                raise ValueError(f"未知的关键词存储类型: {store_type}")
        return self._keyword_store

    def get_llm_router(self) -> LLMRouter:
        if self._llm_router is None:
            self._llm_router = self._build_llm_router()
        return self._llm_router

    def get_pipeline(self) -> QueryPipeline:
        if self._pipeline is None:
            pipeline_type = settings.PIPELINE_TYPE
            if pipeline_type == "naive-rag":
                self._pipeline = NaiveRAGPipeline(
                    vector_store=self.get_vector_store(),
                    keyword_store=self.get_keyword_store(),
                    embedding_model=self.get_embedding_model(),
                    reranker=self.get_reranker(),
                    llm_router=self.get_llm_router(),
                )
            elif pipeline_type == "agentic-rag":
                raise NotImplementedError("Agentic RAG Pipeline 尚未实现")
            else:
                raise ValueError(f"未知的 Pipeline 类型: {pipeline_type}")
        return self._pipeline

    # ========== 初始化 ==========

    async def initialize_all(self):
        """初始化所有服务"""
        logger.info("正在初始化所有服务...")

        # 向量库
        store = self.get_vector_store()
        await store.initialize()
        logger.info(f"向量存储已初始化: {type(store).__name__}")

        # 关键词库
        kw = self.get_keyword_store()
        await kw.initialize()
        logger.info(f"关键词存储已初始化: {type(kw).__name__} ({settings.KEYWORD_STORE_TYPE})")

        # 嵌入模型
        embedding = self.get_embedding_model()
        await embedding.initialize()
        logger.info(f"嵌入模型已初始化: {type(embedding).__name__}")

        # 重排序
        reranker = self.get_reranker()
        await reranker.initialize()
        logger.info(f"重排序已初始化: {type(reranker).__name__}")

        # LLM 路由器 (预创建，不连接)
        self.get_llm_router()
        logger.info(f"LLM 路由器已创建: 主={settings.LLM_PRIMARY_PROVIDER}, "
                     f"备={'启用' if settings.LLM_FALLBACK_ENABLED else '禁用'}")

        # Pipeline
        self.get_pipeline()
        logger.info(f"Pipeline 已创建: {settings.PIPELINE_TYPE}")

        # Redis 缓存
        await conversation_cache.initialize()

        # 事件总线
        await event_bus.initialize()

        self._initialized = True
        logger.info("所有服务初始化完成")

    async def close_all(self):
        """关闭所有服务"""
        logger.info("正在关闭所有服务...")

        if self._milvus_client:
            await self._milvus_client.close()
        if self._keyword_client:
            await self._keyword_client.close()
        if self._llm_router:
            await self._llm_router.close()
        await conversation_cache.close()
        await event_bus.close()

        logger.info("所有服务已关闭")

    # ========== 内部 ==========

    def _build_llm_router(self) -> LLMRouter:
        """构建 LLM 路由器"""
        primary = self._create_provider(
            provider_type=settings.LLM_PRIMARY_PROVIDER,
            is_primary=True,
        )
        fallback = None
        if settings.LLM_FALLBACK_ENABLED:
            fallback = self._create_provider(
                provider_type=settings.LLM_FALLBACK_PROVIDER,
                is_primary=False,
            )
        return LLMRouter(
            primary=primary,
            fallback=fallback,
            max_total_tokens=settings.LLM_MAX_TOTAL_TOKENS,
        )

    def _create_provider(self, provider_type: str, is_primary: bool) -> LLMProvider:
        """创建 LLM 供应商实例"""
        if provider_type == "vllm":
            return VLLMProvider(
                api_base=settings.LLM_VLLM_BASE,
                model_name=settings.LLM_VLLM_MODEL,
                timeout=settings.LLM_TIMEOUT,
                max_retries=settings.LLM_MAX_RETRIES,
            )
        elif provider_type == "deepseek":
            api_key = settings.LLM_DEEPSEEK_API_KEY
            if not api_key:
                api_key = "sk-placeholder"
                if is_primary:
                    logger.warning("DeepSeek API Key 未配置，主模型将不可用")
            return DeepSeekAPIProvider(
                api_key=api_key,
                model_name=settings.LLM_DEEPSEEK_MODEL,
                timeout=settings.LLM_TIMEOUT,
                max_retries=settings.LLM_MAX_RETRIES,
            )
        elif provider_type == "openai":
            return OpenAICompatibleProvider(
                name="openai-api",
                api_base=settings.LLM_OPENAI_BASE,
                api_key=settings.LLM_OPENAI_API_KEY,
                model_name=settings.LLM_OPENAI_MODEL,
                timeout=settings.LLM_TIMEOUT,
                max_retries=settings.LLM_MAX_RETRIES,
            )
        else:
            raise ValueError(f"未知的 LLM 供应商: {provider_type}")


# ========== 全局默认容器 (主进程用) ==========
container = Container()


# ========== FastAPI 依赖注入函数 (同步，不做 IO) ==========

def get_vector_store() -> VectorStore:
    return container.get_vector_store()

def get_keyword_store() -> KeywordStore:
    return container.get_keyword_store()

def get_embedding_model() -> EmbeddingModel:
    return container.get_embedding_model()

def get_reranker() -> Reranker:
    return container.get_reranker()

def get_llm_router() -> LLMRouter:
    return container.get_llm_router()

def get_pipeline() -> QueryPipeline:
    return container.get_pipeline()
