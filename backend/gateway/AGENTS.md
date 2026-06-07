# AGENTS.md — Go API 网关

## 技术栈

Go 1.26.3 + Gin v1.9, 模块路径 `github.com/ai-qa-system/gateway`

## 必须知道的命令

```bash
# 开发运行 (必须在 gateway/ 目录下执行，config.yaml 需在当前目录)
go run cmd/main.go

# 构建
go build -o gateway ./cmd/main.go        # Linux/Mac
go build -o gateway.exe ./cmd/main.go    # Windows

# Docker 构建 (context 必须是项目根目录)
docker build -f deploy/Dockerfile.gateway -t ai-qa-gateway .

# 运行测试
go test ./...  # 23 个测试 (config/JWT/熔断器)
```

## 架构

**API 网关模式 (BFF)** — 不包含业务逻辑，所有请求透明代理到 RAG 服务 (`http://localhost:8001`)。

### 请求流

```
客户端 → gateway:8080 → rag-service:8001
         ├─ 认证 (JWT HS256 + Redis 黑名单)
         ├─ 限流 (令牌桶 100 req/s, 分布式 Redis)
         ├─ 熔断 (客户端级 gobreaker, 分布式 Redis Lua)
         └─ 透传 (X-User-ID, X-User-Role, X-Request-ID)
```

### 关键约定

- **所有 handler 都是代理**: handler 方法只做参数解析 + 调用 `proxyToRAGService()` 或 `proxyToRAGServiceStream()`，不写业务逻辑
- **流式代理**: Chat 端点用 `proxyToRAGServiceStream`，逐行转发 SSE 响应
- **中间件注册顺序不能改**: 审计日志 → 限流 → 认证 → 黑名单 → 代理路由（RequestID → Logging → CORS → RateLimiter → 路由 → Authenticate/AdminRequired）
- **审计日志**: 所有 POST/PUT/DELETE 操作在代理前记录 `AuditLogEntry()`，自动捕获 IP 和 User-Agent
- **错误响应格式**:
  ```json
  {"error": "中文错误信息", "code": "ERROR_CODE"}
  ```
  错误码: `MISSING_TOKEN` / `INVALID_TOKEN` (401), `FORBIDDEN` (403), `RATE_LIMIT_EXCEEDED` (429), `SERVICE_UNAVAILABLE` (502)
- **Token 黑名单**: 登出时将 Token 加入 Redis 黑名单（TTL = Token 剩余有效期），黑名单通过中间件层独立检查

### 熔断器设计

网关支持两层熔断：

| 层级 | 实现 | 粒度 | 说明 |
|------|------|------|------|
| **客户端级** | `gobreaker` 库 | 每进程 | 快速失败，避免无效等待 |
| **分布式** | Redis Lua 脚本 | 跨副本共享 | 全局熔断状态，多副本生效 |

分布式熔断器在主熔断器打开时自动升级为全局熔断，防止多副本各自熔断再各自恢复的震荡。

### 配置

- **来源**: `config.yaml`，必须在运行目录，不支持环境变量覆盖
- 修改端口等配置后需重启服务
- go.mod 中 `pgx`、`redis` 已声明但当前代码未使用（预留依赖，不要轻易删除）

### 目录结构

```
cmd/main.go                — 入口: 加载配置 → 初始化 Gin → 注册中间件 → 启动
internal/
  config/config.go         — 配置结构体 + YAML 加载
  database/database.go     — 数据库连接 (预留)
  handler/
    handler.go             — HTTP handler (全部代理到 RAG)
    circuit_breaker.go     — 客户端熔断器 (gobreaker)
    distributed_breaker.go — 分布式熔断器 (Redis Lua)
  middleware/
    jwt.go                 — JWT 生成/验证 (HS256)
    middleware.go          — RequestID, Logging, CORS, RateLimit, Auth, AdminRequired
    blacklist.go           — Token 黑名单 (Redis)
    metrics.go             — Prometheus 指标
    ratelimit.go           — 限流器
    redis.go               — Redis 客户端连接
  router/router.go         — 路由注册 (公开/需认证/内部三组)
```
