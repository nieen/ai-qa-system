"""
LLM 供应商实现
支持: 本地 vLLM (OpenAI 兼容), DeepSeek API, 通用 OpenAI 兼容 API
"""
import json
import logging
import time
from typing import Any, AsyncGenerator, List, Dict

import httpx

from app.core.protocols import LLMProvider, LLMResponse
from app.core.circuit_breaker import CircuitBreaker, with_retry

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

        async def _stream():
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
                                yield content
                        except json.JSONDecodeError:
                            continue

        try:
            async for token in await with_retry(
                _stream,
                max_retries=self._max_retries,
                circuit_breaker=self._circuit_breaker,
                timeout=self._timeout,
            ):
                yield token
        except Exception as e:
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

        try:
            data = await with_retry(
                _call,
                max_retries=self._max_retries,
                circuit_breaker=self._circuit_breaker,
                timeout=self._timeout,
            )
            latency = int((time.monotonic() - start_time) * 1000)
            choice = data["choices"][0]
            return LLMResponse(
                content=choice["message"]["content"],
                tokens_used=data.get("usage", {}).get("total_tokens", 0),
                model_name=self._model_name,
                latency_ms=latency,
            )
        except Exception as e:
            logger.error(f"LLM 调用失败 [{self._name}]: {e}")
            raise

    async def check_health(self) -> bool:
        try:
            resp = await self._client.get(f"{self._api_base}/models")
            return resp.status_code == 200
        except Exception as e:
            logger.debug(f"健康检查失败 [{self._name}]: {e}")
            return False

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
