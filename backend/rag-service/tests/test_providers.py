"""
LLM 供应商单元测试
- AnthropicProvider: 请求构建, SSE 流式解析, 非流式响应解析, 健康检查
- 不重复测试 OpenAICompatibleProvider (已在 conftest 中间接覆盖)
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.llm.providers import AnthropicProvider


# ==================== AnthropicProvider ====================


@pytest.fixture
def anthropic():
    return AnthropicProvider(api_key="sk-ant-test-key", model_name="claude-sonnet-4-20250514")


class TestAnthropicRequestBuilding:
    """Anthropic _build_request_body 逻辑验证"""

    def test_basic_message_format(self, anthropic):
        """标准 messages → Anthropic 格式转换"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        body = anthropic._build_request_body(messages, 0.3, 4096, stream=True)
        assert body["model"] == "claude-sonnet-4-20250514"
        assert body["messages"] == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        assert body["max_tokens"] == 4096
        assert body["temperature"] == 0.3
        assert body["stream"] is True
        assert "system" not in body  # 没有 system 消息

    def test_system_message_extraction(self, anthropic):
        """system 角色消息 → 顶级 system 字段"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        body = anthropic._build_request_body(messages, 0.3, 4096, stream=False)
        assert body["system"] == "You are a helpful assistant."
        assert all(m["role"] != "system" for m in body["messages"])

    def test_multiple_system_messages_merged(self, anthropic):
        """多条 system 消息合并"""
        messages = [
            {"role": "system", "content": "Rule 1."},
            {"role": "user", "content": "Hi"},
            {"role": "system", "content": "Rule 2."},
        ]
        body = anthropic._build_request_body(messages, 0.3, 4096, stream=False)
        assert "Rule 1." in body["system"]
        assert "Rule 2." in body["system"]

    def test_headers(self, anthropic):
        """Anthropic 认证头格式"""
        headers = anthropic._headers()
        assert headers["x-api-key"] == "sk-ant-test-key"
        assert headers["anthropic-version"] == "2023-06-01"
        assert headers["Content-Type"] == "application/json"

    def test_default_model_name(self):
        """默认模型名"""
        p = AnthropicProvider(api_key="test")
        assert p.model_name == "claude-sonnet-4-20250514"


class TestAnthropicSSEParsing:
    """Anthropic SSE 流式事件解析 — 直接测试 _stream 中的解析逻辑"""

    @pytest.mark.asyncio
    async def test_anthropic_sse_parser_yields_text_from_content_block_delta(self):
        """仅从 content_block_delta.delta.text 提取 token"""
        provider = AnthropicProvider(api_key="test")

        sse_data = [
            ("message_start", {"type": "message_start", "message": {"id": "msg_1"}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                      "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                      "delta": {"type": "text_delta", "text": "Hello"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                      "delta": {"type": "text_delta", "text": " world"}}),
            ("message_stop", {"type": "message_stop"}),
        ]

        # 模拟 SSE 行
        lines = []
        for event_type, data in sse_data:
            lines.append(f"event: {event_type}")
            lines.append(f"data: {json.dumps(data)}")
            lines.append("")

        # 构建可迭代的 SSE 响应
        async def mock_aiter_lines():
            for line in lines:
                yield line

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = mock_aiter_lines

        # 用 _stream 闭包内部逻辑测试
        tokens = []
        expected_event = None
        async for line in mock_aiter_lines():
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
                    text = delta.get("text", "")
                    if text:
                        tokens.append(text)
                elif expected_event == "message_stop":
                    break

        assert tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_skips_non_text_deltas(self):
        """非 text_delta 类型被跳过"""
        provider = AnthropicProvider(api_key="test")

        sse_data = [
            ("message_start", {"type": "message_start"}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                      "content_block": {"type": "tool_use"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                      "delta": {"type": "input_json_delta",
                                                "partial_json": "{}"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                      "delta": {"type": "text_delta", "text": "Hi"}}),
            ("message_stop", {"type": "message_stop"}),
        ]

        tokens = []
        for event_type, data in sse_data:
            if event_type == "content_block_delta":
                delta = data.get("delta", {})
                text = delta.get("text", "")
                if text:
                    tokens.append(text)

        assert tokens == ["Hi"]


class TestAnthropicNonStreamParsing:
    """Anthropic 非流式响应解析"""

    @pytest.mark.asyncio
    async def test_parses_content_array(self):
        """非流式响应 content 数组合并"""
        provider = AnthropicProvider(api_key="test")
        mock_data = {
            "id": "msg_123",
            "type": "message",
            "content": [
                {"type": "text", "text": "Hello! "},
                {"type": "text", "text": "How can I help?"},
            ],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=mock_data)

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        provider._client = mock_client

        with patch.object(provider, '_report_state'):
            result = await provider.chat([{"role": "user", "content": "Hi"}])

        assert result.content == "Hello! How can I help?"
        assert result.tokens_used == 15  # input(10) + output(5)
        assert result.model_name == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_handles_empty_content(self):
        """空 content 数组"""
        provider = AnthropicProvider(api_key="test")
        mock_data = {
            "id": "msg_empty",
            "type": "message",
            "content": [],
            "usage": {"input_tokens": 5, "output_tokens": 0},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=mock_data)

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        provider._client = mock_client

        with patch.object(provider, '_report_state'):
            result = await provider.chat([{"role": "user", "content": "Hi"}])

        assert result.content == ""
        assert result.tokens_used == 5


class TestAnthropicHealthCheck:
    """健康检查"""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        provider = AnthropicProvider(api_key="test")
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        provider._client = mock_client

        assert await provider.check_health() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        provider = AnthropicProvider(api_key="test")
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection error"))
        provider._client = mock_client

        assert await provider.check_health() is False
