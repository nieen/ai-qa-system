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

# 配置日志
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

    logger.info(f"{settings.APP_NAME} 启动完成，端口: {settings.APP_PORT}")
    yield

    # 关闭时清理
    await container.close_all()
    await close_db()
    logger.info(f"{settings.APP_NAME} 已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="企业级 AI 智能问答系统 - RAG 服务",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router, prefix="/api/v1")


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
