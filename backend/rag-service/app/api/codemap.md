# backend/rag-service/app/api/

## 职责

HTTP API 路由层。仅处理请求/响应序列化，业务逻辑委托给 Pipeline + Container。

## 端点

- `POST /api/v1/knowledge-bases/{kb_id}/chat`: 核心问答（SSE 流式），返回 token/metadata/done/error 事件
- `GET/POST /api/v1/knowledge-bases`: 知识库 CRUD
- `POST /api/v1/knowledge-bases/{kb_id}/documents/upload`: 文档上传（Redis Streams 异步索引）
- `GET /api/v1/llm/status`: LLM 供应商状态
- `GET/DELETE /api/v1/admin/users/{user_id}/data`: 用户数据管理（网关调用）
