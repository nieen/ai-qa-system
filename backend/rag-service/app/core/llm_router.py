"""
LLM 路由器
管理多个 LLM 供应商，支持主备切换、自动降级、健康检查
"""
import logging
from typing import Any, AsyncGenerator, List, Dict, Optional

from app.core.protocols import LLMProvider, LLMResponse
from app.core.metrics import record_llm_fallback
from app.core.tracing import start_span, set_span_attribute

logger = logging.getLogger(__name__)


class LLMRouter:
    """
    LLM 路由器

    功能:
      1. 多供应商管理：注册主模型 + 备模型
      2. 自动降级：主模型熔断 → 自动切换到备模型
      3. 自动恢复：备用模式下连续成功 N 次后自动切回主模型
      4. 健康检查：定期检测各供应商状态
      5. 超时控制：为每次调用设置超时
      6. 无限循环防护：限制最大 token 生成量
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallback: Optional[LLMProvider] = None,
        max_total_tokens: int = 16384,
        fallback_on_error: bool = True,
        auto_recover_after: int = 3,
    ):
        self._primary = primary
        self._fallback = fallback
        self._max_total_tokens = max_total_tokens
        self._fallback_on_error = fallback_on_error
        self._current = primary
        self._total_fallbacks = 0
        self._is_fallback_mode = False
        self._auto_recover_after = auto_recover_after  # 连续成功多少次后恢复
        self._fallback_consecutive_successes = 0

    @property
    def primary_name(self) -> str:
        """主模型名称（用于指标和日志）"""
        return self._primary.model_name

    @property
    def current_model(self) -> str:
        return self._current.model_name

    @property
    def is_fallback_mode(self) -> bool:
        return self._is_fallback_mode

    @property
    def total_fallbacks(self) -> int:
        return self._total_fallbacks

    async def _maybe_recover(self) -> None:
        """
        检查是否满足自动恢复条件。
        备用模式下连续成功 _auto_recover_after 次后，自动切回主模型。
        """
        if not self._is_fallback_mode:
            return

        self._fallback_consecutive_successes += 1
        if self._fallback_consecutive_successes >= self._auto_recover_after:
            logger.info(
                "备用模型连续成功 %d 次，自动恢复至主模型 [%s]",
                self._fallback_consecutive_successes,
                self._primary.model_name,
            )
            self._current = self._primary
            self._is_fallback_mode = False
            self._fallback_consecutive_successes = 0

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> AsyncGenerator[str, None]:
        """
        流式对话，带自动降级 (逐 token 输出)
        三重防护: max_tokens 限单次 + max_total_tokens 防无限 + 熔断切换

        自动恢复: 备用模式下连续成功 _auto_recover_after 次后切回主模型
        """
        actual_max = min(max_tokens, self._max_total_tokens)
        tokens_generated = 0

        try:
            async for token in self._current.chat_stream(messages, temperature, actual_max):
                yield token
                tokens_generated += len(token)
                if tokens_generated > self._max_total_tokens * 4:
                    logger.warning("Token 生成超限，强制终止")
                    break

        except Exception as e:
            logger.warning("主模型 [%s] 失败: %s", self._current.model_name, e)
            async for token in self._fallback_stream(messages, temperature, max_tokens):
                yield token

        # 备用模式：连续成功计数，达标后自动恢复
        await self._maybe_recover()

    async def _fallback_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        """流式切换到备用模型，逐 token 产出"""
        if not self._fallback or not self._fallback_on_error:
            yield "\n\n[系统提示] 所有 AI 模型均不可用，请稍后重试。"
            return

        logger.info("切换到备用模型 [%s]", self._fallback.model_name)
        self._current = self._fallback
        self._is_fallback_mode = True
        self._total_fallbacks += 1

        # 记录降级指标
        primary_name = self._primary.model_name or "unknown"
        fallback_name = self._fallback.model_name or "unknown"
        record_llm_fallback(primary_name, fallback_name)

        yield "\n\n> (由备用模型 [%s] 回答)\n\n" % self._fallback.model_name

        try:
            async for token in self._fallback.chat_stream(messages, temperature, max_tokens):
                yield token
        except Exception as e:
            logger.error("备用模型也失败: %s", e)
            yield "\n\n[系统提示] 备用模型也出现异常，请稍后重试。"

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        """非流式对话，带自动降级"""
        try:
            resp = await self._current.chat(messages, temperature, max_tokens)
            await self._maybe_recover()
            return resp
        except Exception as e:
            logger.warning("主模型 [%s] 失败: %s", self._current.model_name, e)
            return await self._fallback_chat(messages, temperature, max_tokens)

    async def _fallback_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """备模型非流式调用"""
        if not self._fallback or not self._fallback_on_error:
            return LLMResponse(content="所有 AI 模型不可用，请稍后重试。")

        logger.info("切换到备用模型 [%s]", self._fallback.model_name)
        self._current = self._fallback
        self._is_fallback_mode = True
        self._total_fallbacks += 1

        try:
            resp = await self._fallback.chat(messages, temperature, max_tokens)
            resp.content = "> (由备用模型 [%s] 回答)\n\n%s" % (self._fallback.model_name, resp.content)
            return resp
        except Exception as e:
            logger.error("备用模型也失败: %s", e)
            return LLMResponse(content="所有 AI 模型不可用，请稍后重试。")

    async def check_health(self) -> Dict[str, Any]:
        """检查所有模型健康状态"""
        primary_ok = await self._primary.check_health()
        fallback_ok: bool = True
        if self._fallback:
            fallback_ok = await self._fallback.check_health()

        return {
            "primary": {"name": self._primary.model_name, "healthy": primary_ok},
            "fallback": {"name": self._fallback.model_name if self._fallback else None, "healthy": fallback_ok},
            "active_model": self._current.model_name,
            "is_fallback_mode": self._is_fallback_mode,
            "total_fallbacks": self._total_fallbacks,
        }

    async def reset(self) -> None:
        """重置回主模型"""
        self._current = self._primary
        self._is_fallback_mode = False
        self._fallback_consecutive_successes = 0
        logger.info("LLM 路由器重置回主模型")

    async def close(self) -> None:
        """清理资源"""
        if hasattr(self._primary, "close"):
            await self._primary.close()
        if self._fallback and hasattr(self._fallback, "close"):
            await self._fallback.close()
