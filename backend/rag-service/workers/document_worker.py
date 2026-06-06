"""
文档索引 Worker
通过 Redis Streams 消费文档索引任务，支持多副本部署

消费者组机制:
  - 多个 worker 副本在同一个消费者组中竞争消费
  - 每条消息只被一个 worker 处理
  - 崩溃的 worker 的未完成消息会被其他 worker 认领 (XCLAIM)
"""
import asyncio
import logging
import os
import signal
import sys
import uuid
from typing import Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from app.core.event_bus import (
    event_bus, STREAM_DOC_INGESTION, GROUP_DOC_WORKERS,
    MAX_DELIVERY_COUNT,
)
from app.ingestion.document_processor import document_processor
from app.core.protocols import Document as DocModel
from app.core.container import container

logging.basicConfig(
    level=getattr(logging, settings.APP_LOG_LEVEL.upper()),
    format="%(asctime)s [%(levelname)s] worker-%(process)d: %(message)s",
)
logger = logging.getLogger("document-worker")

# ==================== 信号处理 ====================

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info(f"收到信号 {signum}，准备优雅关闭...")
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ==================== 核心循环 ====================


async def process_message(msg: dict) -> bool:
    """
    处理单条文档索引消息
    Args:
        msg: 消息字典，包含 id, event_type, data
    Returns:
        True if processed successfully, False otherwise
    """
    data = msg.get("data", {})
    stream_id = msg["id"]

    kb_id = data.get("kb_id", "")
    doc_id = data.get("doc_id", "")
    file_path = data.get("file_path", "")
    file_type = data.get("file_type", "")
    file_name = data.get("file_name", "")

    if not all([kb_id, doc_id, file_path]):
        logger.warning(f"消息参数不完整: {stream_id}")
        return True  # ACK 不完整消息，不阻塞队列

    logger.info(f"开始索引文档 [{file_name}] (doc_id={doc_id}, kb_id={kb_id})")
    await event_bus.publish_doc_status(doc_id, "processing", kb_id, file_name)

    try:
        # Step 1: 解析文档
        chunks = await document_processor.process(file_path, file_type)
        if not chunks:
            logger.warning(f"文档内容为空: {file_name}")
            await event_bus.publish_doc_status(doc_id, "completed", kb_id, file_name, 0)
            return True

        # Step 2: 向量化
        texts = [c["content"] for c in chunks]
        embedding_model = container.get_embedding_model()
        embeddings = await embedding_model.embed_documents(texts)

        # Step 3: 写入 Milvus
        documents = [
            DocModel(
                chunk_id=str(uuid.uuid4()),
                document_id=doc_id,
                kb_id=kb_id,
                chunk_index=c["chunk_index"],
                content=c["content"],
                metadata=c["metadata"],
            )
            for c in chunks
        ]

        vector_store = container.get_vector_store()
        await vector_store.insert(kb_id, documents, embeddings)

        # Step 4: 清理临时文件
        if os.path.exists(file_path):
            os.remove(file_path)

        # Step 5: 发布完成状态
        await event_bus.publish_doc_status(doc_id, "completed", kb_id, file_name, len(chunks))
        logger.info(f"索引完成: {file_name} -> {len(chunks)} 个块")

        return True

    except Exception as e:
        logger.error(f"索引失败 [{file_name}]: {e}", exc_info=True)
        await event_bus.publish_doc_status(doc_id, "failed", kb_id, file_name, error=str(e))
        # 返回 False 表示处理失败，让框架决定是否重试
        return False


async def run_worker(consumer_name: Optional[str] = None):
    """Worker 主循环"""
    worker_id = consumer_name or f"worker-{os.getpid()}"
    logger.info(f"文档索引 Worker 启动 (consumer={worker_id})")
    logger.info(f"  Redis: {settings.REDIS_URL}")
    logger.info(f"  Milvus: {settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
    logger.info(f"  最大重试次数: {MAX_DELIVERY_COUNT}")

    # 初始化基础设施
    await event_bus.initialize()
    await container.initialize_all()

    idle_loops = 0

    while not _shutdown:
        try:
            # 1. 认领超时任务 (崩溃 worker 的遗留任务)
            stale = await event_bus.claim_stale_entries(
                STREAM_DOC_INGESTION, GROUP_DOC_WORKERS, worker_id,
            )
            for msg in stale:
                if _shutdown:
                    break
                success = await process_message(msg)
                await event_bus.ack(STREAM_DOC_INGESTION, GROUP_DOC_WORKERS, msg["id"])

            # 2. 消费新消息
            messages = await event_bus.consume(
                STREAM_DOC_INGESTION, GROUP_DOC_WORKERS, worker_id,
                batch_size=5, block_ms=2000,
            )

            for msg in messages:
                if _shutdown:
                    break
                success = await process_message(msg)
                if success:
                    await event_bus.ack(STREAM_DOC_INGESTION, GROUP_DOC_WORKERS, msg["id"])

            if messages:
                idle_loops = 0
            else:
                idle_loops += 1

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Worker 循环异常: {e}", exc_info=True)
            await asyncio.sleep(5)

    # 优雅关闭
    logger.info("Worker 正在关闭...")
    await container.close_all()
    await event_bus.close()
    logger.info("Worker 已关闭")


def main():
    """入口函数 (用于命令行启动)"""
    consumer_name = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        asyncio.run(run_worker(consumer_name))
    except KeyboardInterrupt:
        logger.info("Worker 被用户中断")


if __name__ == "__main__":
    main()
