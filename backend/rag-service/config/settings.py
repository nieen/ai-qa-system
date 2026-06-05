"""
RAG 服务配置
支持通过环境变量覆盖，优先级: 环境变量 > .env 文件 > 默认值
"""
from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    # --- 应用 ---
    APP_NAME: str = "AI-QA-RAG-Service"
    APP_PORT: int = 8001
    APP_LOG_LEVEL: str = "info"
    APP_LOG_FORMAT: str = "console"  # console | json
    APP_SECRET_KEY: str = "change-this-to-a-random-secret-key"

    # --- 数据库 (PostgreSQL) ---
    POSTGRES_DSN: str = "postgresql+asyncpg://aiqa:aiqa_secure_pass_2026@localhost:5432/aiqa"

    # --- Redis 缓存 ---
    REDIS_ENABLED: bool = True
    REDIS_URL: str = "redis://:aiqa_redis_pass_2026@localhost:6379/0"
    REDIS_CONV_TTL: int = 7200  # 对话缓存 TTL (秒)

    # --- MinIO ---
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "aiqa_admin"
    MINIO_SECRET_KEY: str = "aiqa_minio_pass_2026"
    MINIO_BUCKET: str = "aiqa-documents"
    MINIO_SECURE: bool = False

    # --- Milvus ---
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION_PREFIX: str = "aiqa_"

    # --- 关键词检索 ---
    # 可选: milvus | pgvector | simple
    # milvus = 利用 Milvus 内置 BM25
    # pgvector = PostgreSQL 全文检索 (tsvector)
    # simple  = 轻量级内置 BM25 (无需额外服务)
    KEYWORD_STORE_TYPE: str = "milvus"

    # ============ LLM 多供应商配置 ============

    # --- 主模型 (Primary LLM) ---
    # 可选: vllm | deepseek | openai
    LLM_PRIMARY_PROVIDER: str = "vllm"
    # vLLM 本地
    LLM_VLLM_BASE: str = "http://localhost:8000/v1"
    LLM_VLLM_MODEL: str = "deepseek-r1"
    # DeepSeek 官方 API
    LLM_DEEPSEEK_API_KEY: str = ""
    LLM_DEEPSEEK_MODEL: str = "deepseek-chat"
    # OpenAI 通用兼容
    LLM_OPENAI_BASE: str = ""
    LLM_OPENAI_API_KEY: str = ""
    LLM_OPENAI_MODEL: str = "gpt-4o-mini"

    # --- 备用模型 (Fallback LLM) ---
    LLM_FALLBACK_ENABLED: bool = True
    LLM_FALLBACK_PROVIDER: str = "deepseek"  # 主模型不可用时切换到 DeepSeek API

    # --- LLM 通用参数 ---
    LLM_MAX_TOKENS: int = 8192
    LLM_MAX_TOTAL_TOKENS: int = 16384    # 单次问答最大累计 token (防无限循环)
    LLM_TEMPERATURE: float = 0.3
    LLM_TOP_P: float = 0.9
    LLM_TIMEOUT: float = 60.0            # 单次调用超时 (秒)
    LLM_MAX_RETRIES: int = 2             # 失败重试次数
    LLM_CIRCUIT_BREAKER_THRESHOLD: int = 3  # 连续失败次数触发熔断

    # --- 对话历史 ---
    MAX_VERBATIM_ROUNDS: int = 6         # 对话压缩阈值 (条)
    KEEP_RECENT_ROUNDS: int = 2          # 压缩后保留的最近完整轮次

    # ============ 检索参数 ============

    # --- Embedding ---
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_DEVICE: str = "cuda"
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_MAX_LENGTH: int = 512

    # --- Reranker ---
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANKER_DEVICE: str = "cuda"
    RERANKER_TOP_K: int = 5

    # --- 检索 ---
    RETRIEVAL_TOP_K_VECTOR: int = 30
    RETRIEVAL_TOP_K_BM25: int = 30
    RETRIEVAL_FINAL_TOP_K: int = 5
    RETRIEVAL_SCORE_THRESHOLD: float = 0.3

    # --- Chunk 策略 ---
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64

    # --- Pipeline ---
    # 可选: naive-rag | agentic-rag (Phase 2)
    PIPELINE_TYPE: str = "naive-rag"

    # --- JWT ---
    JWT_SECRET: str = "change-this-to-a-secure-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    # --- CORS ---
    # 逗号分隔的允许来源，默认全放通 (开发环境)
    CORS_ALLOWED_ORIGINS: str = "*"

    # ============ OpenTelemetry 追踪 ============
    OTEL_ENABLED: bool = True
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""  # 空 = 仅日志输出
    OTEL_SERVICE_NAME: str = "rag-service"

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
