"""
事件总线 - Redis Streams 实现
用于跨副本的任务分发和事件通知，零新增基础设施依赖

核心特性:
  - 持久化: 消息写入 Redis RDB/AOF，服务重启不丢失
  - 消费者组: 多副本负载均衡，每条消息只被一个消费者处理
  - 重试机制: Pending Entries + 超时重新入队 (XCLAIM)
  - 进度追踪: 索引完成事件可供 API 轮询查询
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional, Callable, Awaitable

from config.settings import settings

logger = logging.getLogger(__name__)

# ==================== Redis 字段解码 ====================


def _decode_field(v):
    """统一处理 redis-py 与 fakeredis 的字段值类型差异"""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


def _decode_id(msg_id):
    """解码消息 ID"""
    if isinstance(msg_id, bytes):
        return msg_id.decode("utf-8", errors="replace")
    return msg_id


# ==================== Stream 名称常量 ====================

STREAM_DOC_INGESTION = "stream:doc:ingestion"       # 文档索引任务
STREAM_DOC_INGESTION_STATUS = "stream:doc:status"    # 文档索引状态（进度/完成/失败）
STREAM_NOTIFICATION = "stream:notification"           # 跨服务通知

# 消费者组名称
GROUP_DOC_WORKERS = "group:doc-workers"

# 重试配置
MAX_DELIVERY_COUNT = 3           # 最大投递次数
CLAIM_TIMEOUT_MS = 300000        # 300s 后未 ACK 的任务被其他 worker 接管


class EventBus:
    """Redis Streams 事件总线"""

    _redis = None

    async def initialize(self) -> None:
        """初始化 Redis 连接并创建消费者组"""
        if self._redis is not None:
            return

        if not settings.REDIS_ENABLED:
            logger.warning("Redis 禁用，事件总线不可用")
            return

        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5,
            )
            await self._redis.ping()

            # 创建消费者组 (幂等)
            for stream in [STREAM_DOC_INGESTION, STREAM_DOC_INGESTION_STATUS, STREAM_NOTIFICATION]:
                try:
                    await self._redis.xgroup_create(stream, GROUP_DOC_WORKERS, id="0", mkstream=True)
                except Exception as e:
                    if "BUSYGROUP" in str(e):
                        pass  # 组已存在，正常
                    else:
                        logger.debug(f"创建消费者组 {stream} 失败: {e}")

            logger.info("Redis Streams 事件总线初始化完成")
        except Exception as e:
            logger.warning(f"事件总线初始化失败 (降级模式): {e}")
            self._redis = None

    # ==================== 发布 ====================

    async def publish(self, stream: str, event_type: str, data: Dict[str, Any]) -> Optional[str]:
        """
        发布事件到指定 Stream
        Args:
            stream: Stream 名称
            event_type: 事件类型
            data: 事件数据
        Returns:
            message_id: 消息 ID (失败时返回 None)
        """
        if not self._redis:
            logger.warning(f"事件总线不可用，丢弃事件: {event_type}")
            return None

        payload = {
            "event_type": event_type,
            "data": json.dumps(data, ensure_ascii=False),
            "timestamp": str(time.time()),
        }
        try:
            msg_id = await self._redis.xadd(stream, payload, maxlen=10000)
            logger.debug(f"事件发布成功: {stream}/{event_type} -> {msg_id}")
            return msg_id
        except Exception as e:
            logger.error(f"事件发布失败 [{event_type}]: {e}")
            return None

    async def publish_doc_status(
        self, doc_id: str, status: str, kb_id: str = "",
        file_name: str = "", chunk_count: int = 0, error: str = "",
    ) -> Optional[str]:
        """便捷方法: 发布文档索引状态更新"""
        return await self.publish(
            STREAM_DOC_INGESTION_STATUS,
            "doc.status",
            {
                "doc_id": doc_id,
                "status": status,       # processing / completed / failed
                "kb_id": kb_id,
                "file_name": file_name,
                "chunk_count": chunk_count,
                "error": error,
            },
        )

    # ==================== 消费 ====================

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        batch_size: int = 10,
        block_ms: int = 3000,
    ) -> List[Dict[str, Any]]:
        """
        消费 Stream 消息 (阻塞)
        Args:
            stream: Stream 名称
            group: 消费者组名
            consumer: 消费者名称 (每个副本用不同名称)
            batch_size: 每批最大消息数
            block_ms: 阻塞等待时间 (毫秒)
        Returns:
            消息列表，每条包含 id, event_type, data
        """
        if not self._redis:
            return []

        try:
            results = await self._redis.xreadgroup(
                group, consumer,
                {stream: ">"},
                count=batch_size,
                block=block_ms,
            )
        except Exception as e:
            logger.error(f"消费 Stream 失败 [{stream}]: {e}")
            return []

        messages = []
        if results:
            for stream_name, entries in results:
                for msg_id, fields in entries:
                    try:
                        event_type = _decode_field(fields.get(b"event_type", fields.get("event_type", "")))
                        data_raw = _decode_field(fields.get(b"data", fields.get("data", "{}")))
                        ts = _decode_field(fields.get(b"timestamp", fields.get("timestamp", "")))

                        messages.append({
                            "id": _decode_id(msg_id),
                            "event_type": event_type,
                            "data": json.loads(data_raw) if isinstance(data_raw, str) else {},
                            "timestamp": ts,
                        })
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"消息格式错误 [{msg_id}]: {e}")
                        # 格式错误的消息也 ACK，不阻塞队列
                        await self.ack(stream, group, msg_id)
        return messages

    # ==================== ACK / 重试 ====================

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        """确认消息已处理完成"""
        if not self._redis:
            return
        try:
            await self._redis.xack(stream, group, msg_id)
        except Exception as e:
            logger.warning(f"ACK 失败 [{msg_id}]: {e}")

    async def claim_stale_entries(
        self, stream: str, group: str, consumer: str,
        min_idle_time_ms: int = CLAIM_TIMEOUT_MS,
    ) -> List[Dict[str, Any]]:
        """
        认领超时未 ACK 的消息 (死信重试)
        防止某个 worker 崩溃后任务永远不被处理
        """
        if not self._redis:
            return []

        try:
            # 获取 Pending Entries 摘要
            pending = await self._redis.xpending(stream, group)
            if not pending or pending["pending"] == 0:
                return []

            # 获取具体的 Pending 消息
            details = await self._redis.xpending_range(
                stream, group, min="-", max="+", count=20,
            )
        except Exception as e:
            logger.debug(f"查询 Pending Entries 失败: {e}")
            return []

        claimed = []
        for entry in details:
            if entry["times_delivered"] >= MAX_DELIVERY_COUNT:
                # 超过最大重试次数 → 标记为死信
                logger.warning(
                    f"消息 {entry['message_id']} 已达最大重试次数 ({MAX_DELIVERY_COUNT})，标记为死信"
                )
                await self.ack(stream, group, entry["message_id"])
                continue

            if entry["time_since_delivered"] * 1000 >= min_idle_time_ms:
                # 超时未 ACK → 认领
                try:
                    result = await self._redis.xclaim(
                        stream, group, consumer, min_idle_time_ms,
                        [entry["message_id"]],
                    )
                    for msg_id, fields in result or []:
                        claimed.append({
                            "id": _decode_id(msg_id),
                            "event_type": _decode_field(fields.get(b"event_type", fields.get("event_type", ""))),
                            "data": json.loads(
                                _decode_field(fields.get(b"data", fields.get("data", "{}")))
                            ),
                            "timestamp": _decode_field(fields.get(b"timestamp", fields.get("timestamp", ""))),
                            "delivery_count": entry["times_delivered"] + 1,
                        })
                except Exception as e:
                    logger.debug(f"认领消息失败 [{entry['message_id']}]: {e}")

        return claimed

    # ==================== 状态查询 ====================

    async def get_doc_status(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        查询文档索引进度
        遍历 STREAM_DOC_INGESTION_STATUS 获取最新状态
        """
        if not self._redis:
            return None

        try:
            # 反向读取最近的 100 条状态消息
            entries = await self._redis.xrevrange(
                STREAM_DOC_INGESTION_STATUS,
                max="+", min="-", count=100,
            )
            for msg_id, fields in entries:
                try:
                    data_raw = _decode_field(fields.get(b"data", fields.get("data", "{}")))
                    data = json.loads(data_raw) if isinstance(data_raw, str) else {}
                    if data.get("doc_id") == doc_id:
                        return {
                            "doc_id": doc_id,
                            "status": data.get("status"),
                            "file_name": data.get("file_name"),
                            "chunk_count": data.get("chunk_count", 0),
                            "error": data.get("error"),
                        }
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            logger.warning(f"查询文档状态失败 [{doc_id}]: {e}")

        return None

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()
            self._redis = None


# 全局单例
event_bus = EventBus()
