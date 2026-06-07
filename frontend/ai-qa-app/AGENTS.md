# AGENTS.md — Next.js 前端

本目录是 `ai-qa-system` 仓库的前端子项目，详见根目录 [AGENTS.md](../../AGENTS.md)。

## 技术栈

Next.js 16.2 (App Router) + React 19 + TypeScript strict + Tailwind CSS 3 + Vitest

## 背景

前端是企业 AI 智能问答系统的用户界面。LLM 全部通过后端 API 接入，前端不涉及任何模型推理。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8080/api/v1` | Go API 网关地址 |

## 必须知道的命令

```bash
npm run dev          # 开发服务器 → localhost:3000
npm run build        # 生产构建 (含 tsc --noEmit 类型检查)
npm run lint         # ESLint (next/core-web-vitals + next/typescript)
npm run test         # Vitest 单元测试 (24 个)
npm run test:watch   # Vitest 监听模式
```

## 目录结构

```
src/
├── app/
│   ├── layout.tsx          # 全局布局 (字体、Metadata)
│   └── page.tsx            # 首页: 顶栏 + 认证 + 主题 + 聊天界面
├── components/
│   ├── ChatInterface.tsx   # 聊天主组件 (消息列表 + 输入区 + 来源展示)
│   ├── AuthModal.tsx       # 认证模态框 (登录/注册/隐私政策)
│   └── ui/
│       ├── button.tsx      # UI Button (forwardRef + cn)
│       └── input.tsx       # UI Input (forwardRef + cn)
├── hooks/
│   ├── useChat.ts          # 聊天状态管理 (messages, send, streaming, sources)
│   └── useDocumentUpload.ts # 文档上传 + 轮询状态
├── lib/
│   ├── api.ts              # API 客户端 (认证/知识库/文档/问答/管理)
│   ├── auth.ts             # 认证管理 (Token localStorage + authHeaders)
│   └── utils.ts            # 工具函数 (cn, formatBytes 等)
└── test/
    ├── setup.ts            # Vitest 测试设置 (jsdom + msw 可选)
    ├── auth.test.ts        # auth 模块测试
    ├── api.test.ts         # API 客户端测试
    └── utils.test.ts       # 工具函数测试
```

## 关键约定

### 路径别名

`@/` 映射到 `src/*`，始终使用别名导入：
```ts
import { ChatInterface } from "@/components/ChatInterface"
import { api } from "@/lib/api"
```
不要用相对路径 `../components/...`

### API 调用

**浏览器通过 Next.js API Routes (BFF) 同源请求 /api/***，无 CORS：
```ts
// src/lib/api.ts
const API_PREFIX = "/api"  // 浏览器端，同源
```
```ts
// src/app/api/[...path]/route.ts  (服务端转发)
const API_BASE = process.env.API_BASE || "http://gateway:8080/api/v1"
```

**认证流程:**

**已实现完整认证**（非占位）：
1. `login()` / `register()` — POST 到网关，获取 JWT Token
2. Token 存储于 localStorage，`authHeaders()` 注入所有请求
3. `logout()` — 调用网关 POST /user/logout 加入 Redis 黑名单
4. 401 自动清除 Token，抛出 `AuthError`
5. 页面初始化时从 localStorage 恢复登录状态

### SSE 流式处理

`chatStream()` 是核心 UX 模式，使用 `fetch` + `ReadableStream` reader：
```ts
const reader = response.body?.getReader()
// 解析 SSE: data: {"type": "token"|"metadata"|"done"|"error", ...}
```
不要改用 EventSource（不支持 POST），不要改成 WebSocket（后端不支持）。

### 自定义 Hooks

| Hook | 用途 | 关键行为 |
|------|------|---------|
| `useChat` | 聊天状态管理 | send() 触发 SSE 流式请求，管理 messages/streaming/sources/conversationId |
| `useDocumentUpload` | 文档上传 | upload() 上传后自动轮询状态 (2s 间隔, 60s 超时) |

### 样式

- 纯 Tailwind CSS 类，CSS 变量定义在 `globals.css`
- **暗色模式**: Tailwind `darkMode: "class"`，通过 `useTheme` hook 切换 (light/dark/system)
- `cn()` 工具函数 (clsx + tailwind-merge)：`import { cn } from "@/lib/utils"`
- 组件变体: 手写 class-variance-authority 模式，类似 shadcn/ui 但没有用 shadcn CLI 生成
- Markdown 渲染: `react-markdown` + `remark-gfm`，配合 `prose` 类

### 数据合规 (PIPL)

| 功能 | API 端点 | 说明 |
|------|---------|------|
| 导出个人数据 | `POST /user/export` | PIPL §45 数据可携带权 |
| 请求删除账号 | `POST /user/delete-request` | PIPL §47 删除权，7 天冷静期 |
| 确认删除 | `POST /user/delete-request/:id/confirm` | 冷静期后确认 |
| 取消删除 | `POST /user/delete-request/:id/cancel` | 冷静期内取消 |

### 组件模式

UI 组件在 `src/components/ui/`，使用 `React.forwardRef` + `cn()` + Tailwind：
```tsx
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    return <button className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />
  }
)
```
新增 UI 组件必须遵循此模式。

### 安全

- **CSP**: `next.config.mjs` 配置 Content-Security-Policy 头
- **X-Content-Type-Options**: nosniff
- **X-Frame-Options**: DENY
- **认证错误处理**: 401 自动清除 Token，引导重新登录

### 可访问性

- `aria-live="polite"` — 消息区域和状态提示
- `role="dialog"` / `aria-modal="true"` — 模态框
- `autoFocus` — 输入框和模态框自动聚焦
- 主题切换按钮有 `aria-label`

### 没有的东西

- **无状态管理库**: 全部用 `useState`/`useRef`/`useEffect`/自定义 hooks，如需全局状态需要自行引入 zustand 或 context
- **单页应用**: 仅 `/` 一个路由，知识库通过 `kbId` prop 切换
- **无路由守卫**: 认证状态在 page.tsx 中管理，未登录时显示登录界面
