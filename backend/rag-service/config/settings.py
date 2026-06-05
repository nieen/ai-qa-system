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

    # ============ LLM 配置 ============
    #
    # 设计原则: 按 API 协议区分, 不按部署模式区分
    #
    # API 格式 (LLM_API_FORMAT):
    #   "openai"    → OpenAI 兼容格式 (/v1/chat/completions)
    #                 适用于: vLLM, OpenAI, DeepSeek, Ollama, Groq 等
    #   "anthropic" → Anthropic Messages 格式 (/v1/messages)
    #                 适用于: Claude 系列
    #
    # 供应商 (LLM_PROVIDER):
    #   用于设置默认端点、API Key 策略、指标标签
    #   "openai"    → https://api.openai.com/v1 (需 Key)
    #   "deepseek"  → https://api.deepseek.com (需 Key)
    #   "vllm"      → http://localhost:8000/v1 (无需 Key)
    #   "ollama"    → http://localhost:11434/v1 (无需 Key)
    #   "anthropic" → https://api.anthropic.com/v1 (需 Key)

    # --- 主模型 ---
    LLM_API_FORMAT: str = "openai"          # openai | anthropic
    LLM_PROVIDER: str = "vllm"              # 供应商名 (默认端点/Key策略/标签)
    LLM_MODEL: str = "deepseek-r1"          # 模型名
    LLM_BASE_URL: str = ""                  # API 端点 (留空自动推导)
    LLM_API_KEY: str = ""                   # API Key (留空自动推导)

    # --- 多模态 ---
    LLM_SUPPORTS_MULTIMODAL: bool = False   # 模型是否支持图片输入

    # --- 思考/推理模式 ---
    LLM_THINKING_ENABLED: bool = False      # 是否启用思考模式
    LLM_THINKING_BUDGET: int = 2048         # 思考 token 预算

    # --- 备用模型 (主模型不可用时自动切换) ---
    LLM_FALLBACK_ENABLED: bool = True
    LLM_FALLBACK_API_FORMAT: str = "openai"
    LLM_FALLBACK_PROVIDER: str = "deepseek"
    LLM_FALLBACK_MODEL: str = "deepseek-chat"
    LLM_FALLBACK_BASE_URL: str = ""
    LLM_FALLBACK_API_KEY: str = ""
    LLM_FALLBACK_THINKING_ENABLED: bool = False
    LLM_FALLBACK_THINKING_BUDGET: int = 1024

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
    EMBEDDING_MODEL: str = "shibing624/text2vec-base-chinese"
    EMBEDDING_DIM: int = 768
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
