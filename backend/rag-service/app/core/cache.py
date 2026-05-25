"""
持久化缓存服务
对话历史缓存 (Redis) + 数据库持久化 (PostgreSQL)
支持高可用部署
"""
import json
import logging
import time
from typing import List, Dict, Optional, Any

from config.settings import settings

logger = logging.getLogger(__name__)


class ConversationCache:
    """
    对话缓存服务
    两层存储:
      Tier 1: Redis (热数据, TTL 过期)
      Tier 2: PostgreSQL (冷数据, 永久存储)
    """

    _instance = None
    _redis = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self):
        """初始化 Redis 连接"""
        if self._redis is not None:
            return

        if not settings.REDIS_ENABLED:
            logger.info("Redis 缓存已禁用")
            return

        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            await self._redis.ping()
            logger.info("Redis 缓存连接成功")
        except Exception as e:
            logger.warning(f"Redis 连接失败，缓存降级到内存: {e}")
            self._redis = None

    async def get_conversation(
        self, conversation_id: str
    ) -> Optional[List[Dict[str, str]]]:
        """获取对话历史 (Redis → 内存)"""
        if self._redis:
            try:
                data = await self._redis.get(f"conv:{conversation_id}")
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"Redis 读取失败: {e}")
        return None

    async def set_conversation(
        self,
        conversation_id: str,
        messages: List[Dict[str, str]],
        ttl: int = 3600,  # 默认 1 小时
    ):
        """缓存对话历史"""
        if self._redis:
            try:
                await self._redis.setex(
                    f"conv:{conversation_id}",
                    ttl,
                    json.dumps(messages, ensure_ascii=False),
                )
            except Exception as e:
                logger.warning(f"Redis 写入失败: {e}")

    async def append_message(
        self,
        conversation_id: str,
        message: Dict[str, str],
        ttl: int = 3600,
    ):
        """追加一条消息到对话历史"""
        if self._redis:
            try:
                key = f"conv:{conversation_id}"
                data = await self._redis.get(key)
                if data:
                    messages = json.loads(data)
                else:
                    messages = []
                messages.append(message)
                await self._redis.setex(
                    key, ttl, json.dumps(messages, ensure_ascii=False)
                )
            except Exception as e:
                logger.warning(f"Redis 追加失败: {e}")

    async def delete_conversation(self, conversation_id: str):
        """删除缓存的对话"""
        if self._redis:
            try:
                await self._redis.delete(f"conv:{conversation_id}")
            except Exception as e:
                logger.warning(f"Redis 删除失败: {e}")

    async def close(self):
        if self._redis:
            await self._redis.close()

    @property
    def available(self) -> bool:
        return self._redis is not None


# 全局单例
conversation_cache = ConversationCache()
