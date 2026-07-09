# frontend/ai-qa-app/src/app/api/[...path]/

## 职责

BFF（Backend For Frontend）API 路由。catch-all 处理器，将所有 `/api/*` 请求转发到 Go API 网关。

## 设计

- 同源代理：浏览器请求 `/api/*` → Next.js 服务端 → Go 网关:8080
- 流式响应：Chat 端点识别（`path.includes("/chat")`）→ 透传 SSE 流
- 超时控制：非流式请求 30s 超时，流式不断开
- 认证透传：`Authorization` Header 原样转发
