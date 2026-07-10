# 仓库图谱: ai-qa-system

## 项目职责

基于 **LLM + RAG** 架构的企业级 AI 智能问答平台。所有 LLM 通过 API 接入（DeepSeek / Claude / OpenAI），不部署本地推理模型。三个子项目独立部署，通过 HTTP API 通信。

## 系统入口

- `backend/gateway/cmd/main.go`: Go API 网关入口，加载配置 → 初始化 Gin → 注册中间件 → 启动 HTTP 服务器
- `backend/rag-service/app/main.py`: Python RAG 服务入口，FastAPI 应用生命周期管理 + 依赖注入容器初始化
- `frontend/ai-qa-app/src/app/page.tsx`: Next.js 前端入口，浏览器端渲染的首页组件

## 目录聚合

| 目录 | 职责概要 | 详细图谱 |
|------|---------|---------|
| `backend/gateway/` | Go API 网关 — 认证/限流/熔断/请求代理到 RAG 服务 | [查看图谱](backend/gateway/codemap.md) |
| `backend/rag-service/` | Python RAG 服务 — 文档索引/向量检索/LLM 问答编排 | [查看图谱](backend/rag-service/codemap.md) |
| `frontend/ai-qa-app/` | Next.js 前端 — 用户界面/BFF 代理层/认证管理 | [查看图谱](frontend/ai-qa-app/codemap.md) |
| `deploy/` | 部署配置 — Docker/Docker Compose/数据库迁移/基础设施 | [查看图谱](deploy/codemap.md) |

## 数据流

```
浏览器 → /api/* → Next.js BFF → Go 网关:8080 → RAG 服务:8001 → Milvus + PG + Redis
         ↑                                    ↑
   同源请求，无 CORS                   认证/限流/熔断
```

## 集成点

- **Go 网关 ↔ RAG 服务**: HTTP 代理，通过 `X-User-ID` / `X-User-Role` Header 透传用户信息
- **RAG 服务 ↔ Milvus**: gRPC 向量检索
- **网关 + RAG 共享 PostgreSQL**: 不同数据库实例（`aiqa_gateway` / `aiqa_rag`），通过 migration 管理 DDL
- **Redis**: 网关用做 Token 黑名单/分布式限流/熔断，RAG 服务用做对话缓存/事件总线
