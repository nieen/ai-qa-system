"""
企业级 AI 智能问答系统 - RAG 服务入口
提供文档索引、向量检索、问答生成等核心能力
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config.settings import settings
from app.api.routes import router as api_router
from app.core.database import init_db, close_db
from app.core.container import container
from app.core.cache import conversation_cache
from app.core.event_bus import event_bus
from app.core.metrics import register_metrics_endpoint
from app.core.tracing import setup_tracing, instrument_app, shutdown_tracing

# 配置日志 - JSON 结构化输出 (生产环境)
if settings.APP_LOG_FORMAT == "json":
    import json as json_module

    class JSONFormatter(logging.Formatter):
        """JSON 日志格式化器"""
        def format(self, record):
            log_entry = {
                "timestamp": self.formatTime(record),
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0]:
                log_entry["exception"] = self.formatException(record.exc_info)
            return json_module.dumps(log_entry, ensure_ascii=False)

    _handler = logging.StreamHandler()
    _handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=getattr(logging, settings.APP_LOG_LEVEL.upper()), handlers=[_handler])
else:
    logging.basicConfig(
        level=getattr(logging, settings.APP_LOG_LEVEL.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理"""
    logger.info(f"启动 {settings.APP_NAME}...")
    logger.info(f"  Pipeline: {settings.PIPELINE_TYPE}")
    logger.info(f"  LLM 主模型: {settings.LLM_PRIMARY_PROVIDER}/{settings.LLM_VLLM_MODEL}")
    logger.info(f"  LLM 备用: {'启用' if settings.LLM_FALLBACK_ENABLED else '禁用'} ({settings.LLM_FALLBACK_PROVIDER})")
    logger.info(f"  Redis 缓存: {'启用' if settings.REDIS_ENABLED else '禁用'}")

    # 启动时初始化 (使用容器统一管理)
    await init_db()
    await container.initialize_all()

    # 初始化 OpenTelemetry 追踪
    tracing_ok = setup_tracing()
    if tracing_ok:
        instrument_app(app)

    logger.info(f"{settings.APP_NAME} 启动完成，端口: {settings.APP_PORT}")
    yield

    # 关闭时清理
    shutdown_tracing()
    await container.close_all()
    await close_db()
    logger.info(f"{settings.APP_NAME} 已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="""企业级 AI 智能问答系统 - RAG 服务

提供文档索引、向量检索、混合检索（稠密语义 + BM25 关键词）、
Reranker 重排序、LLM 流式问答等核心 RAG 能力。

## 认证说明
用户认证由 Go API 网关处理，RAG 服务不参与认证。
已认证用户信息通过 `X-User-ID` / `X-User-Role` Header 透传。

## 异步任务
文档索引通过 Redis Streams 实现异步处理，支持多副本 Worker 负载均衡。

## 相关服务
- **API 网关**: http://localhost:8080 (管理/认证/限流)
- **Swagger 文档**: http://localhost:8001/docs (本服务)
- **Prometheus 指标**: http://localhost:8001/metrics
""",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={
        "name": "AI QA System Team",
        "url": "https://github.com/nieen/ai-qa-system",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
)

# CORS 配置
# "*" 允许所有来源（开发环境），此时 allow_credentials 必须为 False
# 逗号分隔的域名列表（生产环境），allow_credentials 正常工作
raw_origins = settings.CORS_ALLOWED_ORIGINS
if raw_origins == "*":
    cors_origins = ["*"]
    allow_creds = False
else:
    cors_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
    allow_creds = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_creds,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

# 注册路由
app.include_router(api_router, prefix="/api/v1")

# 注册指标端点 (Prometheus)
register_metrics_endpoint(app)


@app.get("/health")
async def health_check():
    """增强版健康检查"""
    llm_router = container.get_llm_router()
    llm_health = await llm_router.check_health()
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "pipeline": settings.PIPELINE_TYPE,
        "llm": llm_health,
        "redis_available": conversation_cache.available,
    }


@app.get("/health/llm")
async def llm_health_check():
    """LLM 健康检查详情"""
    llm_router = container.get_llm_router()
    return await llm_router.check_health()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.APP_PORT,
        reload=False,
        log_level=settings.APP_LOG_LEVEL,
    )
