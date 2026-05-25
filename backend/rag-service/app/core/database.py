"""
数据库连接管理 (PostgreSQL)
"""
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config.settings import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.POSTGRES_DSN,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db():
    """初始化数据库连接"""
    try:
        # 测试连接
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        logger.info("数据库连接成功")
    except Exception as e:
        logger.warning(f"数据库连接失败: {e}")
        logger.warning("服务将继续运行，但数据库相关功能将不可用")


async def close_db():
    """关闭数据库连接"""
    await engine.dispose()
    logger.info("数据库连接已关闭")


async def get_db() -> AsyncSession:
    """获取数据库会话 (依赖注入用)"""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
