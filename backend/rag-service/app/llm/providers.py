"""
LLM 供应商实现
支持两种 API 协议格式:
  - OpenAI 格式: 通过 OpenAICompatibleProvider (vLLM, OpenAI, DeepSeek, Ollama...)
  - Anthropic 格式: 通过 AnthropicProvider (Claude 系列, Messages API)

通过 settings 配置:
  LLM_API_FORMAT="openai" | "anthropic"   # 选择协议
  LLM_PROVIDER="vllm" | "openai" | ...    # 设置默认端点/Key策略
  LLM_MODEL="deepseek-r1" | "gpt-4o"      # 模型名
"""
import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, List, Dict, Optional

import httpx

from app.core.protocols import LLMProvider, LLMResponse
from app.core.circuit_breaker import CircuitBreaker, with_retry
from app.core.tracing import start_span, set_span_attribute, record_exception
from app.core.metrics import (
    record_llm_call, record_llm_stream_call,
    record_circuit_breaker_state,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """
    通用 OpenAI 兼容 API 供应商
    适用于所有 /v1/chat/completions 接口: vLLM, Ollama, DeepSeek, OpenAI, Groq...

    与 Anthropic 格式的核心差异:
      - 端点: /v1/chat/completions
      - 认证: Authorization: Bearer
      - SSE: data: {"choices":[{"delta":{"content":"..."}}]} / data: [DONE]
      - 响应: choices[0].message.content
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
        thinking_enabled: bool = False,
        thinking_budget: int = 2048,
    ) -> None:
        self._name = name
        self._model_name = model_name
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p
        self._timeout = timeout
        self._max_retries = max_retries
        self._thinking_enabled = thinking_enabled
        self._thinking_budget = thinking_budget
        self._circuit_breaker = CircuitBreaker(
            name=f"llm:{name}",
            failure_threshold=3,
            recovery_timeout=30.0,
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

        self._last_state_report = 0.0
        self._report_state(0)

    @property
    def model_name(self) -> str:
        return self._model_name

    def _reasoning_effort(self) -> Optional[str]:
        """将 thinking_budget 映射到 OpenAI reasoning_effort 参数"""
        if not self._thinking_enabled:
            return None
        if self._thinking_budget < 1024:
            return "low"
        elif self._thinking_budget < 4096:
            return "medium"
        return "high"

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
            body = self._build_request_body(messages, temperature, max_tokens, stream=True)
            async with self._client.stream(
                "POST", url,
                headers=self._headers(),
                json=body,
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
            "api_format": "openai",
            "thinking_enabled": self._thinking_enabled,
            "messages_count": len(messages),
        }):
            try:
                async for token in await with_retry(
                    _stream,
                    max_retries=self._max_retries,
                    circuit_breaker=self._circuit_breaker,
                    timeout=self._timeout,
                ):
                    yield token

                latency_ms = (time.monotonic() - call_start) * 1000
                ttf_ms = (first_token_time - call_start) * 1000 if first_token_time > 0 else 0
                record_llm_stream_call(self._name, "success", latency_ms, ttf_ms)
                set_span_attribute("llm.tokens", token_count)
                set_span_attribute("llm.latency_ms", latency_ms)
                set_span_attribute("llm.ttf_ms", ttf_ms)
                self._report_state(0)

            except Exception as e:
                latency_ms = (time.monotonic() - call_start) * 1000
                record_llm_stream_call(self._name, "error", latency_ms)
                record_exception(e)
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
            body = self._build_request_body(messages, temperature, max_tokens, stream=False)
            resp = await self._client.post(
                url,
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data

        with start_span("llm.chat", {
            "provider": self._name,
            "model": self._model_name,
            "api_format": "openai",
            "thinking_enabled": self._thinking_enabled,
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


class AnthropicProvider(LLMProvider):
    """
    Anthropic Messages API 供应商
    适用于: Claude 3/3.5/4 系列 (Sonnet, Haiku, Opus)

    API 文档: https://docs.anthropic.com/en/api/messages

    与 OpenAI 格式的核心差异:
      - 端点: /v1/messages (非 /chat/completions)
      - 认证: x-api-key header (非 Authorization Bearer)
      - 请求: max_tokens 为必填字段
      - system 消息 → 顶级字段, 不在 messages 数组中
      - 流式: event/data 交替行, token 从 content_block_delta.delta.text 提取
      - 非流式: content 数组格式: [{"type":"text","text":"..."}]
      - 思考模式: 通过 thinking 字段开启 (extended thinking)
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
        temperature: float = 0.3,
        top_p: float = 0.9,
        timeout: float = 60.0,
        max_retries: int = 2,
        thinking_enabled: bool = False,
        thinking_budget: int = 2048,
    ) -> None:
        self._name = f"anthropic-{model_name}"
        self._api_base = "https://api.anthropic.com/v1"
        self._model_name = model_name
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p
        self._timeout = timeout
        self._max_retries = max_retries
        self._thinking_enabled = thinking_enabled
        self._thinking_budget = thinking_budget
        self._circuit_breaker = CircuitBreaker(
            name=f"llm:anthropic:{model_name}",
            failure_threshold=3,
            recovery_timeout=30.0,
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        self._last_state_report = 0.0
        self._report_state(0)

    @property
    def model_name(self) -> str:
        return self._model_name

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _build_request_body(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict:
        """构建 Anthropic Messages API 请求体。"""
        system_content = None
        api_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                if system_content is None:
                    system_content = msg.get("content", "")
                else:
                    system_content += "\n" + msg.get("content", "")
                continue
            api_messages.append({
                "role": msg["role"],
                "content": msg.get("content", ""),
            })

        body: dict = {
            "model": self._model_name,
            "messages": api_messages,
            "max_tokens": max_tokens or self._max_tokens,
            "temperature": temperature or self._temperature,
            "stream": stream,
        }

        if system_content:
            body["system"] = system_content

        # 思考模式 (Anthropic Extended Thinking)
        if self._thinking_enabled:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._thinking_budget,
            }
            # 启用 thinking 时 max_tokens 必须大于 budget_tokens
            body["max_tokens"] = max(body["max_tokens"], self._thinking_budget + 1024)

        return body

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> AsyncGenerator[str, None]:
        url = f"{self._api_base}/messages"
        call_start = time.monotonic()
        first_token_time: float = 0.0
        token_count = 0

        async def _stream():
            nonlocal first_token_time, token_count
            body = self._build_request_body(messages, temperature, max_tokens, stream=True)
            async with self._client.stream(
                "POST", url,
                headers=self._headers(),
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    raise RuntimeError(
                        f"Anthropic API 错误 ({resp.status_code}): {error_text}"
                    )

                expected_event = None
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        expected_event = None
                        continue
                    if line.startswith("event: "):
                        expected_event = line[7:].strip()
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if expected_event == "content_block_delta":
                            delta = data.get("delta", {})
                            # 普通文本: delta.type == "text_delta"
                            # 思考内容: delta.type == "thinking_delta"
                            text = delta.get("text", "")
                            if text:
                                if first_token_time == 0:
                                    first_token_time = time.monotonic()
                                token_count += 1
                                yield text
                        elif expected_event == "message_stop":
                            break

        with start_span("llm.chat_stream", {
            "provider": self._name,
            "model": self._model_name,
            "api_format": "anthropic",
            "thinking_enabled": self._thinking_enabled,
            "messages_count": len(messages),
        }):
            try:
                async for token in await with_retry(
                    _stream,
                    max_retries=self._max_retries,
                    circuit_breaker=self._circuit_breaker,
                    timeout=self._timeout,
                ):
                    yield token

                latency_ms = (time.monotonic() - call_start) * 1000
                ttf_ms = (first_token_time - call_start) * 1000 if first_token_time > 0 else 0
                record_llm_stream_call(self._name, "success", latency_ms, ttf_ms)
                set_span_attribute("llm.tokens", token_count)
                set_span_attribute("llm.latency_ms", latency_ms)
                set_span_attribute("llm.ttf_ms", ttf_ms)
                self._report_state(0)

            except Exception as e:
                latency_ms = (time.monotonic() - call_start) * 1000
                record_llm_stream_call(self._name, "error", latency_ms)
                record_exception(e)
                if self._circuit_breaker.is_open():
                    self._report_state(2)
                logger.error(f"Anthropic 流式调用失败 [{self._name}]: {e}")
                raise

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        url = f"{self._api_base}/messages"
        start_time = time.monotonic()

        async def _call():
            body = self._build_request_body(messages, temperature, max_tokens, stream=False)
            resp = await self._client.post(
                url,
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

        with start_span("llm.chat", {
            "provider": self._name,
            "model": self._model_name,
            "api_format": "anthropic",
            "thinking_enabled": self._thinking_enabled,
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

                content_parts = data.get("content", [])
                full_content = "".join(
                    block["text"] for block in content_parts if block.get("type") == "text"
                )
                usage = data.get("usage", {})

                response = LLMResponse(
                    content=full_content,
                    tokens_used=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                    model_name=data.get("model", self._model_name),
                    latency_ms=latency,
                )

                record_llm_call(
                    provider=self._name,
                    model=self._model_name,
                    result="success",
                    latency_ms=latency,
                    tokens_total=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                    tokens_prompt=usage.get("input_tokens", 0),
                    tokens_completion=usage.get("output_tokens", 0),
                )
                set_span_attribute("llm.latency_ms", latency)
                set_span_attribute("llm.tokens.total",
                                   usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
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
                logger.error(f"Anthropic 调用失败 [{self._name}]: {e}")
                raise

    async def check_health(self) -> bool:
        try:
            resp = await self._client.get(
                "https://api.anthropic.com/v1/models",
                headers=self._headers(),
            )
            return resp.status_code == 200
        except Exception as e:
            logger.debug(f"Anthropic 健康检查失败 [{self._name}]: {e}")
            return False

    def _report_state(self, state: int):
        now = time.monotonic()
        if now - self._last_state_report < 30.0:
            return
        self._last_state_report = now
        record_circuit_breaker_state(self._name, state)

    async def close(self) -> None:
        await self._client.aclose()
