# frontend/ai-qa-app/src/lib/

## 职责

工具库层。封装 API 调用、认证管理和通用工具函数。

## 模块

- `api.ts`: API 客户端
  - 所有请求走同源 `/api/*`（Next.js BFF）
  - `authFetch()`: 带认证的 fetch，自动处理 401 清除 Token
  - `chatStream()`: SSE 流式解析（ReadableStream reader）
  - 完整 API 覆盖: 认证/用户/知识库/文档/问答/管理
- `auth.ts`: 认证管理
  - JWT Token 存储在 localStorage
  - `authHeaders()`: 注入 `Authorization: Bearer <token>`
  - `clearToken()`: 登出时清除 localStorage
- `utils.ts`: 工具函数 — `cn()`（clsx + tailwind-merge）、`formatBytes()` 等
