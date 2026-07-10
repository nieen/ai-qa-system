# frontend/ai-qa-app/src/app/

## 职责

Next.js App Router 页面层。包含全局布局（layout.tsx）、首页（page.tsx）和 BFF API 路由（api/）。

## 组件

- `layout.tsx`: 全局布局 — Geist 字体加载、Metadata 配置
- `page.tsx`: 首页 — 顶栏（认证状态/主题切换/PIPL 操作）/ 聊天主体 / AuthModal
- `globals.css`: 全局样式 + CSS 变量 + Tailwind 指令
- `api/[...path]/route.ts`: BFF 代理，转发所有 `/api/*` 请求到 Go 网关
