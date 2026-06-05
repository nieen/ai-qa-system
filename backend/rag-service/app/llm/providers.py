"""
LLM 供应商实现
支持: 本地 vLLM (OpenAI 兼容), DeepSeek API, 通用 OpenAI 兼容 API
"""
import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, List, Dict

import httpx

from app.core.protocols import LLMProvider, LLMResponse
from app.core.circuit_breaker import CircuitBreaker, with_retry
from app.core.tracing import start_span, set_span_attribute, record_exception
from app.core.metrics import (
    record_llm_call, record_llm_stream_call, record_llm_fallback,
    record_circuit_breaker_state,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """
    通用 OpenAI 兼容 API 供应商
    适用于: vLLM, Ollama, DeepSeek, OpenAI, Anthropic 等
    """

    def __init__(
        self,
        name: str,
        api_base: str,
        api_key: str,
        model_name: str,
        max_tokens: int = 8192,
        temperature: float = 0.3,
        top_p: float = 0.9,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self._model_name = model_name
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p
        self._timeout = timeout
        self._max_retries = max_retries
        self._name = name
        self._circuit_breaker = CircuitBreaker(
            name=f"llm:{name}",
            failure_threshold=3,    # 连续 3 次失败开启熔断
            recovery_timeout=30.0,  # 30 秒后尝试恢复
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

        # 熔断器状态跟踪 (每 30 秒同步到 Prometheus)
        self._last_state_report = 0.0
        self._report_state(0)

    @property
    def model_name(self) -> str:
        return self._model_name

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> AsyncGenerator[str, None]:
        url = f"{self._api_base}/chat/completions"
        call_start = time.monotonic()
        first_token_time: float = 0.0
        token_count = 0

        async def _stream():
            nonlocal first_token_time, token_count
            async with self._client.stream(
                "POST", url,
                headers=self._headers(),
                json={
                    "model": self._model_name,
                    "messages": messages,
                    "temperature": temperature or self._temperature,
                    "max_tokens": max_tokens or self._max_tokens,
                    "top_p": self._top_p,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    raise RuntimeError(
                        f"LLM API 错误 ({resp.status_code}): {error_text}"
                    )
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                if first_token_time == 0:
                                    first_token_time = time.monotonic()
                                token_count += 1
                                yield content
                        except json.JSONDecodeError:
                            continue

        with start_span("llm.chat_stream", {
            "provider": self._name,
            "model": self._model_name,
            "messages_count": len(messages),
            "message_chars": sum(len(m.get("content", "")) for m in messages),
        }):
            try:
                async for token in await with_retry(
                    _stream,
                    max_retries=self._max_retries,
                    circuit_breaker=self._circuit_breaker,
                    timeout=self._timeout,
                ):
                    yield token

                # 成功 — 记录指标
                latency_ms = (time.monotonic() - call_start) * 1000
                ttf_ms = (first_token_time - call_start) * 1000 if first_token_time > 0 else 0
                record_llm_stream_call(self._name, "success", latency_ms, ttf_ms)
                set_span_attribute("llm.tokens", token_count)
                set_span_attribute("llm.latency_ms", latency_ms)
                set_span_attribute("llm.ttf_ms", ttf_ms)
                self._report_state(0)

            except Exception as e:
                # 失败 — 记录指标
                latency_ms = (time.monotonic() - call_start) * 1000
                record_llm_stream_call(self._name, "error", latency_ms)
                record_exception(e)
                # 熔断器状态
                if self._circuit_breaker.is_open():
                    self._report_state(2)
                logger.error(f"LLM 流式调用失败 [{self._name}]: {e}")
                raise

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        url = f"{self._api_base}/chat/completions"
        start_time = time.monotonic()

        async def _call():
            resp = await self._client.post(
                url,
                headers=self._headers(),
                json={
                    "model": self._model_name,
                    "messages": messages,
                    "temperature": temperature or self._temperature,
                    "max_tokens": max_tokens or self._max_tokens,
                    "top_p": self._top_p,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data

        with start_span("llm.chat", {
            "provider": self._name,
            "model": self._model_name,
            "messages_count": len(messages),
        }):
            try:
                data = await with_retry(
                    _call,
                    max_retries=self._max_retries,
                    circuit_breaker=self._circuit_breaker,
                    timeout=self._timeout,
                )
                latency = int((time.monotonic() - start_time) * 1000)
                choice = data["choices"][0]
                usage = data.get("usage", {})

                response = LLMResponse(
                    content=choice["message"]["content"],
                    tokens_used=usage.get("total_tokens", 0),
                    model_name=self._model_name,
                    latency_ms=latency,
                )

                # 记录指标
                record_llm_call(
                    provider=self._name,
                    model=self._model_name,
                    result="success",
                    latency_ms=latency,
                    tokens_total=usage.get("total_tokens", 0),
                    tokens_prompt=usage.get("prompt_tokens", 0),
                    tokens_completion=usage.get("completion_tokens", 0),
                )
                set_span_attribute("llm.latency_ms", latency)
                set_span_attribute("llm.tokens.total", usage.get("total_tokens", 0))
                self._report_state(0)

                return response

            except Exception as e:
                latency = int((time.monotonic() - start_time) * 1000)
                record_llm_call(
                    provider=self._name,
                    model=self._model_name,
                    result="error",
                    latency_ms=latency,
                )
                record_exception(e)
                if self._circuit_breaker.is_open():
                    self._report_state(2)
                logger.error(f"LLM 调用失败 [{self._name}]: {e}")
                raise

    async def check_health(self) -> bool:
        try:
            resp = await self._client.get(f"{self._api_base}/models")
            return resp.status_code == 200
        except Exception as e:
            logger.debug(f"健康检查失败 [{self._name}]: {e}")
            return False

    def _report_state(self, state: int):
        """上报熔断器状态到 Prometheus (限频)"""
        now = time.monotonic()
        if now - self._last_state_report < 30.0:
            return
        self._last_state_report = now
        record_circuit_breaker_state(self._name, state)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def close(self) -> None:
        await self._client.aclose()


class DeepSeekAPIProvider(OpenAICompatibleProvider):
    """
    DeepSeek 官方 API 供应商
    API 地址固定为 https://api.deepseek.com
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "deepseek-chat",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="deepseek-api",
            api_base="https://api.deepseek.com",
            api_key=api_key,
            model_name=model_name,
            timeout=120.0,
            **kwargs,
        )


class VLLMProvider(OpenAICompatibleProvider):
    """
    本地 vLLM 供应商
    """

    def __init__(
        self,
        api_base: str = "http://localhost:8000",
        model_name: str = "deepseek-r1",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            name="vllm-local",
            api_base=api_base,
            api_key="not-needed",  # vLLM 本地不需要 key
            model_name=model_name,
            timeout=120.0,
            **kwargs,
        )
