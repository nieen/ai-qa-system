# backend/gateway/internal/router/

## 职责

路由注册器。负责组装完整依赖树（Repository → Service → Proxy → Handler）并注册到 Gin 引擎。

## 设计

三组路由：
1. **公开端点**（`/api/v1/auth/login`, `/api/v1/auth/register`）— 无需认证
2. **需认证端点**（`/api/v1/user/*`, `/api/v1/knowledge-bases/*`, `/api/v1/conversations/*`, `/api/v1/admin/*`）— 经过 JWT 中间件
3. **内部路由**（`/internal/api/v1/health`）— 服务间调用

知识库 CRUD 使用通用 `Forward` 方法透明代理到 RAG 服务。
