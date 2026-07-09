# frontend/ai-qa-app/src/test/

## Responsibility

前端单元测试目录，覆盖 API 通信、认证逻辑、工具函数三类核心模块。使用 Vitest 作为测试运行器，@testing-library/jest-dom 提供 DOM 断言扩展。

## Design

各测试文件按被测模块组织，与 `src/lib/` 结构对应：

| 文件 | 测试目标 | 覆盖范围 |
|------|---------|---------|
| `api.test.ts` | `src/lib/api.ts` | SSE 流式问答 (`chatStream`)、HTTP 错误处理 (`AuthError`)、认证 Header 集成 |
| `auth.test.ts` | `src/lib/auth.ts` | Token 存取 (`getToken`/`setToken`/`clearToken`)、登录状态判断 (`isAuthenticated`)、角色检查 (`isAdmin`) |
| `utils.test.ts` | `src/lib/utils.ts` | Tailwind class 合并 (`cn` — 条件类/冲突解析/空输入) |
| `setup.ts` | JSDOM 环境 | 引入 `@testing-library/jest-dom` 扩展 DOM 匹配器 |

## Integration

- 所有测试在 `vitest.config.ts` 配置的 JSDOM 环境中运行
- `api.test.ts` 使用 `vi.mock()` mock `auth` 模块 + `global.fetch` mock SSE 流
- `auth.test.ts` 操作 `localStorage`（JSDOM 模拟），测试前后用 `beforeEach` 清理状态

