"""
熔断器 + 重试 + 超时控制
为外部服务调用提供容错能力，支持高可用部署
"""
import asyncio
import enum
import logging
import time
from typing import Any, Optional, Callable, Awaitable, Dict

logger = logging.getLogger(__name__)


class CircuitState(enum.Enum):
    CLOSED = "closed"        # 正常工作
    OPEN = "open"            # 熔断开启，快速失败
    HALF_OPEN = "half_open"  # 半开，允许少量请求探测


class CircuitBreaker:
    """
    熔断器
    当连续失败达到阈值，快速失败而不调用实际服务
    经过恢复时间后进入半开状态，允许探测请求
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_requests: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_requests = half_open_max_requests

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_requests = 0
        self._total_failures = 0
        self._total_successes = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_requests = 0
                logger.info(f"[熔断器] {self.name}: OPEN → HALF_OPEN (恢复超时)")
        return self._state

    def is_open(self) -> bool:
        """快速检查是否处于熔断开启状态"""
        return self.state == CircuitState.OPEN

    async def call(self, fn: Callable[..., Awaitable], *args, **kwargs):
        """执行受保护调用"""
        state = self.state

        if state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(
                f"[熔断器] {self.name}: 熔断开启中，快速拒绝"
            )

        if state == CircuitState.HALF_OPEN:
            if self._half_open_requests >= self.half_open_max_requests:
                raise CircuitBreakerOpenError(
                    f"[熔断器] {self.name}: 半开状态限流中"
                )
            self._half_open_requests += 1

        try:
            result = await fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._half_open_requests = 0
        self._total_successes += 1

    def _on_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        self._total_failures += 1
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                f"[熔断器] {self.name}: CLOSED → OPEN "
                f"(连续 {self._failure_count} 次失败)"
            )

    def reset(self):
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_requests = 0
        logger.info(f"[熔断器] {self.name}: 手动重置")

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "total_successes": self._total_successes,
            "total_failures": self._total_failures,
            "failure_threshold": self.failure_threshold,
        }


class CircuitBreakerOpenError(Exception):
    """熔断器开启异常"""
    pass


async def with_retry(
    fn: Callable[..., Awaitable],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    circuit_breaker: Optional[CircuitBreaker] = None,
    timeout: Optional[float] = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    带重试 + 熔断 + 超时的调用包装

    Args:
        fn: 异步函数
        max_retries: 最大重试次数
        base_delay: 基础退避延迟秒数
        max_delay: 最大退避延迟
        circuit_breaker: 熔断器
        timeout: 超时秒数 (None = 不超时)
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            if circuit_breaker:
                result = await circuit_breaker.call(
                    _call_with_timeout, fn, timeout, *args, **kwargs
                )
            else:
                result = await _call_with_timeout(fn, timeout, *args, **kwargs)
            return result

        except CircuitBreakerOpenError:
            raise  # 熔断开启，不重试

        except asyncio.TimeoutError as e:
            last_exception = e
            logger.warning(
                f"调用超时 (attempt {attempt + 1}/{max_retries + 1}): {fn.__name__}"
            )

        except Exception as e:
            last_exception = e
            logger.warning(
                f"调用失败 (attempt {attempt + 1}/{max_retries + 1}): {fn.__name__} - {e}"
            )

        if attempt < max_retries:
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.info(f"等待 {delay:.1f}s 后重试...")
            await asyncio.sleep(delay)

    raise last_exception or RuntimeError("重试耗尽但无异常信息")


async def _call_with_timeout(fn: Callable[..., Awaitable], timeout: Optional[float], *args: Any, **kwargs: Any) -> Any:
    """带超时的调用包装"""
    if timeout:
        return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
    return await fn(*args, **kwargs)
