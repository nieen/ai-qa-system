# AGENTS.md — Next.js 前端

## 技术栈

Next.js 14.2 (App Router) + React 18 + TypeScript strict + Tailwind CSS 3

## 必须知道的命令

```bash
npm run dev      # 开发服务器 → localhost:3000
npm run build    # 生产构建
npm run lint     # ESLint (next/core-web-vitals + next/typescript)
# 无 test 脚本
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

**无 Next.js rewrites/代理**，前端通过环境变量直接调用后端：
```ts
// src/lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080/api/v1"
```
开发时需要后端 CORS 放行 `localhost:3000`。默认连 gatey:8080。

### SSE 流式处理

`chatStream()` 是核心 UX 模式，使用 `fetch` + `ReadableStream` reader：
```ts
const reader = response.body?.getReader()
// 解析 SSE: data: {"type": "token"|"metadata"|"done"|"error", ...}
```
不要改用 EventSource（不支持 POST），不要改成 WebSocket（后端不支持）。

### 样式

- 纯 Tailwind CSS 类，CSS 变量定义在 `globals.css`
- `cn()` 工具函数 (clsx + tailwind-merge)：`import { cn } from "@/lib/utils"`
- 组件变体: 手写 class-variance-authority 模式，类似 shadcn/ui 但没有用 shadcn CLI 生成
- Markdown 渲染: `react-markdown` + `remark-gfm`，配合 `prose` 类

### 没有的东西

- **无认证实现**: `login()` API 函数存在但未被任何组件调用，无 token 存储、无路由守卫、无 middleware.ts
- **无状态管理库**: 全部用 `useState`/`useRef`/`useEffect`，如需全局状态需要自行引入 zustand 或 context
- **无测试框架**: 需要从零搭建
- **单页应用**: 仅 `/` 一个路由，知识库通过 `kbId` prop 切换

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
