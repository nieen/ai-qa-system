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
import time
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
from app.core.storage import storage_client
from workers.metrics import (
    init_worker_metrics, record_message_processed, record_processing_step,
    update_pending_messages, update_idle_loops, set_worker_stopped,
)

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


async def process_message(msg: dict, worker_id: str = "unknown") -> bool:
    """
    处理单条文档索引消息
    Args:
        msg: 消息字典，包含 id, event_type, data
    Returns:
        True if processed successfully, False otherwise
    """
    data = msg.get("data", {})
    stream_id = msg["id"]
    event_type = msg.get("event_type", "doc.index")

    kb_id = data.get("kb_id", "")
    doc_id = data.get("doc_id", "")
    file_path = data.get("file_path", "")
    file_type = data.get("file_type", "")
    file_name = data.get("file_name", "")

    # 如果消息包含 MinIO 对象路径，优先从 MinIO 下载，并记录下载耗时
    minio_object = data.get("minio_object", "")
    if minio_object and settings.MINIO_ENDPOINT != "localhost:9000":
        local_path = f"tmp/{uuid.uuid4()}_{file_name}"
        os.makedirs("tmp", exist_ok=True)
        success = await storage_client.download(settings.MINIO_BUCKET, minio_object, local_path)
        if success:
            file_path = local_path
            logger.info(f"已从 MinIO 下载: {minio_object} -> {local_path}")

    if not all([kb_id, doc_id, file_path]):
        logger.warning(f"消息参数不完整: {stream_id}")
        return True  # ACK 不完整消息，不阻塞队列

    logger.info(f"开始索引文档 [{file_name}] (doc_id={doc_id}, kb_id={kb_id})")
    await event_bus.publish_doc_status(doc_id, "processing", kb_id, file_name)

    msg_start = time.monotonic()
    try:
        # Step 1: 解析文档
        step_start = time.monotonic()
        chunks = await document_processor.process(file_path, file_type)
        record_processing_step(worker_id, "parse", (time.monotonic() - step_start) * 1000)
        if not chunks:
            logger.warning(f"文档内容为空: {file_name}")
            await event_bus.publish_doc_status(doc_id, "completed", kb_id, file_name, 0)
            record_message_processed(worker_id, "skipped", (time.monotonic() - msg_start) * 1000)
            return True

        # Step 2: 向量化
        step_start = time.monotonic()
        texts = [c["content"] for c in chunks]
        embedding_model = container.get_embedding_model()
        embeddings = await embedding_model.embed_documents(texts)
        record_processing_step(worker_id, "embed", (time.monotonic() - step_start) * 1000)

        # Step 3: 写入 Milvus
        step_start = time.monotonic()
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
        record_processing_step(worker_id, "insert", (time.monotonic() - step_start) * 1000)

        # Step 4: 清理临时文件（仅清理本地临时下载的文件，保留 MinIO 持久化存储）
        if file_path.startswith("tmp/") and os.path.exists(file_path):
            os.remove(file_path)

        # Step 5: 发布完成状态
        await event_bus.publish_doc_status(doc_id, "completed", kb_id, file_name, len(chunks))
        total_ms = (time.monotonic() - msg_start) * 1000
        record_message_processed(worker_id, "success", total_ms)
        logger.info(f"索引完成: {file_name} -> {len(chunks)} 个块 (耗时 {total_ms:.0f}ms)")

        return True

    except Exception as e:
        total_ms = (time.monotonic() - msg_start) * 1000
        logger.error(f"索引失败 [{file_name}]: {e} (耗时 {total_ms:.0f}ms)", exc_info=True)
        await event_bus.publish_doc_status(doc_id, "failed", kb_id, file_name, error=str(e))
        record_message_processed(worker_id, "failed", total_ms)
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

    # 初始化 Prometheus 指标（Worker 无 HTTP 端口，启动独立端口 9101）
    init_worker_metrics(worker_id, metrics_port=9101)

    idle_loops = 0
    pending_check_interval = 30  # 每 30 次空闲循环检查一次待处理消息数

    while not _shutdown:
        try:
            # 1. 认领超时任务 (崩溃 worker 的遗留任务)
            stale = await event_bus.claim_stale_entries(
                STREAM_DOC_INGESTION, GROUP_DOC_WORKERS, worker_id,
            )
            for msg in stale:
                if _shutdown:
                    break
                success = await process_message(msg, worker_id)
                await event_bus.ack(STREAM_DOC_INGESTION, GROUP_DOC_WORKERS, msg["id"])

            # 2. 消费新消息
            messages = await event_bus.consume(
                STREAM_DOC_INGESTION, GROUP_DOC_WORKERS, worker_id,
                batch_size=5, block_ms=2000,
            )

            for msg in messages:
                if _shutdown:
                    break
                success = await process_message(msg, worker_id)
                if success:
                    await event_bus.ack(STREAM_DOC_INGESTION, GROUP_DOC_WORKERS, msg["id"])

            if messages:
                idle_loops = 0
            else:
                idle_loops += 1

            # 3. 周期性收集待处理消息数 (每 30 次循环)
            if idle_loops > 0 and idle_loops % pending_check_interval == 0:
                try:
                    pending = await event_bus.get_pending_count(
                        STREAM_DOC_INGESTION, GROUP_DOC_WORKERS,
                    )
                    update_pending_messages(STREAM_DOC_INGESTION, GROUP_DOC_WORKERS, pending)
                except Exception as e:
                    logger.debug(f"获取待处理消息数失败: {e}")

            # 更新空闲指标
            update_idle_loops(worker_id, idle_loops)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Worker 循环异常: {e}", exc_info=True)
            await asyncio.sleep(5)

    # 优雅关闭
    logger.info("Worker 正在关闭...")
    set_worker_stopped(worker_id)
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
