# frontend/ai-qa-app/

## 职责

Next.js 16 + React 19 + Tailwind CSS 前端应用。通过 BFF 模式（Next.js API Routes）同源请求 Go 网关，无 CORS 问题。

## 设计

- 单页应用（仅 `/` 路由），认证状态在 page.tsx 中管理
- 浏览器 → `/api/*` → Next.js BFF → Go 网关:8080 → RAG 服务:8001
- 完整 JWT 认证（登录/注册/Token 黑名单登出）
- SSE 流式问答（fetch + ReadableStream 解析）
- 暗色模式（Tailwind `darkMode: "class"`）
- 数据合规（PIPL §45 数据导出, §47 删除权）

## 目录聚合

| 目录 | 职责概要 |
|------|---------|
| `src/app/` | App Router 页面 + BFF API 路由 |
| `src/components/` | React 组件 — ChatInterface / AuthModal / UI 组件 |
| `src/hooks/` | 自定义 Hooks — useChat / useDocumentUpload |
| `src/lib/` | 工具库 — API 客户端 / 认证管理 / 工具函数 |
