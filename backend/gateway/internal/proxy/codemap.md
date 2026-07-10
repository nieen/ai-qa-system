# backend/gateway/internal/proxy/

## 职责

RAG 服务代理客户端层。封装 HTTP 调用、熔断器、重试、审计日志等逻辑。

## 设计

- `client.go`: RAGProxyClient — 管理 HTTP 连接池、构建请求、重试（指数退避 + 随机抖动）、SSE 流式转发、文件上传代理
- `circuit_breaker.go`: 客户端级熔断器（gobreaker），每进程快速失败
- `distributed_breaker.go`: 分布式熔断器（Redis Lua 脚本），跨副本共享熔断状态

## 数据流

```
Handler → RAGProxyClient.Request() → 熔断检查 → HTTP 调用 → 重试逻辑 → 响应回写
```

- 请求失败时调用 `breaker.Failure()`，成功调用 `breaker.Success()`
- SSE 流式请求（Chat）通过 `RequestStream` 逐行转发
