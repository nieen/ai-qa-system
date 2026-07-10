# backend/gateway/

## 职责

Go API 网关层（BFF 模式），所有请求由网关代理到 RAG 服务。网关不包含业务逻辑，负责认证（JWT HS256）、限流（令牌桶）、熔断（gobreaker + Redis Lua）、请求透传。

## 设计

分层架构（Handler → Service → Repository），所有 handler 都是透明代理。

## 数据流

```
客户端 → Gin Engine → 中间件链 → Router → Handler → RAGProxy → RAG 服务
         ├─ RequestID        ├─ /auth/login     ├─ proxyToRAGService
         ├─ Logging          ├─ /knowledge-     └─ proxyToRAGServiceStream
         ├─ CORS               bases/*
         ├─ RateLimiter      ├─ /user/profile
         ├─ Authenticate     └─ /admin/stats
         └─ Blacklist
```

## 目录聚合

| 目录 | 职责概要 |
|------|---------|
| `cmd/` | 入口文件 — main.go + migrate 工具 |
| `internal/config/` | 配置结构体 + YAML 加载 + 环境变量覆盖 |
| `internal/database/` | PostgreSQL 连接管理 + 查询方法 |
| `internal/handler/` | HTTP 处理器 — 参数解析 + 代理调用 |
| `internal/middleware/` | Gin 中间件 — RequestID/Logging/CORS/RateLimit/Auth/Blacklist/Metrics |
| `internal/proxy/` | RAG 服务代理客户端 + 熔断器 |
| `internal/repository/` | 数据访问接口定义 |
| `internal/router/` | 路由注册 — 组装依赖树 |
| `internal/service/` | 业务服务接口 + 实现 |
