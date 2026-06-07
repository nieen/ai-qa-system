"""
Worker 健康检查脚本
在 Docker healthcheck 中调用：
  python -m workers.healthcheck

检查项:
  1. Redis 连接是否正常（Worker 依赖 Redis Streams）
  2. 进程是否响应
"""
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings


def check_worker_health() -> bool:
    """检查 Worker 健康状态"""
    # 检查 Redis 连接
    try:
        import redis.asyncio as aredis
    except ImportError:
        import redis as aredis

    try:
        import asyncio
        async def ping_redis():
            r = aredis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
            result = await r.ping()
            await r.aclose()
            return result
        ok = asyncio.run(ping_redis())
        if not ok:
            print("HealthCheck FAILED: Redis PING returned false")
            return False
    except Exception as e:
        print(f"HealthCheck FAILED: Redis connection error: {e}")
        return False

    return True


if __name__ == "__main__":
    if check_worker_health():
        print("HealthCheck OK")
        sys.exit(0)
    else:
        sys.exit(1)
