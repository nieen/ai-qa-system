# 企业 AI 智能问答系统

[![Go](https://img.shields.io/badge/Go-1.26-00ADD8)](https://go.dev/)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB)](https://python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688)](https://fastapi.tiangolo.com/)
[![Milvus](https://img.shields.io/badge/Milvus-2.5-00A1EA)](https://milvus.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

基于 **LLM + RAG** 的企业级智能问答平台。纯本地私有化部署（不含 LLM 推理），LLM 全部通过 API 接入。

## 核心功能

- **多源知识库** — 支持 PDF / Word / Markdown / HTML / 纯文本 自动解析索引
- **智能问答** — SSE 流式输出（打字机效果），支持 Markdown 渲染 + 来源引用
- **混合检索** — 稠密向量（BGE-M3）+ BM25 关键词 + RRF 融合 + BGE-Reranker 精排
- **多 LLM 供应商** — DeepSeek（推荐）/ Claude / OpenAI，支持自动降级和交叉备用
- **完整治理** — JWT 认证 + RBAC 权限 + 审计日志 + PIPL 数据合规（导出/删除）
- **高可用** — Redis 分布式限流 + 分布式熔断器 + 多副本文档 Worker

## 快速启动

```bash
# 1. 配置环境变量
cp .env.example .env       # 编辑 .env 填入 LLM API Key

# 2. 启动基础设施（PostgreSQL / Redis / Milvus / MinIO）
bash make.sh infra

# 3. 执行数据库迁移（统一入口，自动处理网关 + RAG 两个库）
bash make.sh db-migrate

# 4. 启动 RAG 服务（uvicorn 热重载）
bash make.sh dev-rag &

# 5. 启动 API 网关（air 热重载）
bash make.sh dev-gateway &

# 6. 启动前端
cd frontend/ai-qa-app && npm install && npm run dev
```

> 一键启动: `bash make.sh dev` (启动基础设施后提示手动开三个终端)<br>
> 一键部署: `bash make.sh deploy` (git pull → infra → migrate → build → up)

## 架构一览

```
                              ┌─────────────────┐
                              │   Next.js 前端    │
                              │  localhost:3000   │
                              └────────┬────────┘
                                       │ HTTP/SSE
                              ┌────────▼────────┐
                              │   Go API 网关     │
                              │  认证/审计/限流    │
                              │  代理/熔断/PIPL   │
                              └──┬────┬────┬────┘
                                 │    │    │
                     ┌───────────┘    │    └───────────┐
                     ▼                ▼                ▼
            ┌────────────────┐ ┌──────────┐ ┌────────────────┐
            │  PostgreSQL     │ │  Redis   │ │  RAG 服务       │
            │  用户/审计/PIPL  │ │ 限流/黑名单│ │  文档索引+检索   │
            │  对话/文档/知识库│ │ 熔断器    │ │  localhost:8001 │
            │  (同一实例)      │ │ Streams  │ └──┬────┬────┬───┘
            └────────────────┘ └──────────┘    │    │    │
                                         ┌──────┘    │    └──────┐
                                         ▼           ▼           ▼
                                 ┌──────────┐ ┌──────────┐ ┌──────────┐
                                 │  Milvus   │ │  MinIO   │ │  LLM API │
                                 │ 向量检索   │ │ 文档存储  │ │ DeepSeek/│
                                 └──────────┘ └──────────┘ │ Claude/  │
                                                           │ OpenAI   │
                                                           └──────────┘
```

> **数据流说明**: PostgreSQL 和 Redis 是**两个服务共用**。
> - **PostgreSQL**: 网关管理用户账户/审计日志/PIPL 数据；RAG 管理对话/文档/知识库元数据。(同一实例)
> - **Redis**: 网关用于限流/Token 黑名单/分布式熔断器；RAG 用于文档索引 Streams/对话缓存。">

## 技术栈

| 层 | 技术 |
|----|------|
| LLM | DeepSeek / Claude / OpenAI（全部 API 接入） |
| 嵌入/重排 | BGE-M3 + BGE-Reranker（本地 GPU/CPU） |
| 向量库 | Milvus 2.5 |
| API 网关 | Go 1.26.3 + Gin |
| RAG 服务 | Python 3.13+ + FastAPI 0.136.3 |
| 前端 | Next.js 16.2 + React 19 + Tailwind CSS 3 |
| 存储 | PostgreSQL 16 + Redis 7 + MinIO |
| 测试 | Vitest（前端 24）+ pytest（后端 75）+ Go test（网关 23） |

## 文档导航

| 文档 | 说明 |
|------|------|
| [AGENTS.md](AGENTS.md) | AI Agent 工作标准（项目约束、代码约定） |
| [ROADMAP.md](ROADMAP.md) | 项目发展规划（Phase 2/3/4 路线图） |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构与设计详解 |
| [部署手册](docs/deployment-manual.md) | 环境要求、部署步骤、运维指南 |
| [用户手册](docs/user-manual.md) | 功能操作、界面说明、常见问题 |

## License

MIT
