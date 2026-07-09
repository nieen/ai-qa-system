# backend/gateway/internal/middleware/

## 职责

Gin 中间件链。注册顺序不能改：RequestID → Logging → CORS → RateLimiter → Router → Authenticate → AdminRequired。

## 组件

- `middleware.go`: RequestID（UUID 注入）、Logging（请求日志）、CORS、RateLimiter（本地/Redis 令牌桶）、Authenticate（JWT 验证 + Token 黑名单检查）、AdminRequired（角色校验）
- `jwt.go`: JWT 签发/验证（HS256），含 Token 黑名单检查
- `rateLimit.go`: 令牌桶限流器（本地内存 / Redis 分布式）
- `blacklist.go`: 登出 Token 黑名单（Redis，TTL = Token 剩余有效期）
- `metrics.go`: Prometheus 指标端点
- `redis.go`: Redis 客户端连接管理
