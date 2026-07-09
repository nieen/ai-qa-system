# frontend/ai-qa-app/src/hooks/

## 职责

自定义 React Hooks。封装有状态逻辑，组件层不直接管理状态。

## Hooks

- `useChat.ts`: 聊天状态管理
  - `send(question)`: 发送消息 → SSE 流式接收 → 逐 token 更新 / metadata / sources / error / done
  - `clear()`: 清空对话 + 重置 conversationId
  - 使用 ref 持有最新 messages，避免闭包捕获过时状态
- `useDocumentUpload.ts`: 文档上传
  - `upload(file)`: POST 上传 → 轮询状态（2s 间隔, 60s 超时）
  - 状态机: idle → uploading → processing → completed/failed/timeout
