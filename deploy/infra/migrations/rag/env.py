"""
Alembic 环境配置 — RAG 服务 (aiqa_rag 数据库)

自动迁移模式需要 ORM Model 定义，当前使用手动 SQL 迁移。
当新增 ORM Model 时，可在此文件导入 Base 并启用 run_async() 的 autogenerate。
"""
import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 如需 ORM 自动迁移，在此导入 Base 和所有 Model:
# from app.core.database import Base
# from app.models import *  # noqa
# target_metadata = Base.metadata
target_metadata = None  # 当前使用手动 SQL 迁移


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本但不连接数据库"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式：直连数据库执行迁移"""
    from config.settings import settings

    dsn = settings.POSTGRES_DSN
    connectable = create_async_engine(dsn, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """运行在线迁移"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
