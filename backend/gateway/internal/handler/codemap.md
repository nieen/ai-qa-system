# backend/gateway/internal/handler/

## 职责

HTTP 处理器层。所有 handler 只做参数解析 + 调用 proxy/RAG API，不写业务逻辑。

## 设计

- `new_handler.go`: Handler 结构体 + NewHandler 构造函数
- `dto.go`: 请求/响应 DTO 定义
- `auth_handler.go`: 登录/注册端点
- `user_handler.go`: 用户资料/PIPL 合规（数据导出/删除）
- `admin_handler.go`: 管理员功能（用户管理/审计日志/系统统计/数据清理）
- `proxy_handler.go`: 通用 Forward 方法（透明代理到 RAG）+ 健康检查 + UploadDocument / Chat
- `handler.go`: 已废弃，仅保留避免 git 删除历史

## 数据流

1. 请求到达 → 参数校验 → 调用 Service 层或 Proxy 层
2. Chat 端点通过 `proxyToRAGServiceStream` 实现 SSE 流式转发
3. 知识库 CRUD 通过 `Forward` 通用方法直接透传
