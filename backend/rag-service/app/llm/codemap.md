# backend/rag-service/app/llm/

## 职责

LLM 提供商实现。支持 OpenAI 兼容 API 和 Anthropic API 两种协议。

## 组件

- `llm_service.py`: LLM 服务 — 系统提示模板、上下文压缩、历史摘要
- `providers.py`: Provider 实现
  - `OpenAICompatibleProvider`: 兼容 OpenAI / DeepSeek / vLLM / Ollama / Groq 等
  - `AnthropicProvider`: Anthropic Claude API（支持 Thinking）
