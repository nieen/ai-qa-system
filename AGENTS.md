# AGENTS.md — 企业 AI 智能问答系统

> 本文档是项目的**唯一主文档**，所有项目信息统一在此。子项目 AGENTS.md 仅包含各自的特有信息。

## 项目概述

基于 **LLM + RAG** 的企业级智能问答平台，纯本地私有化部署（不含 LLM 推理），LLM 全部通过 API 接入，支持 DeepSeek / Claude / OpenAI 等供应商，支持 PDF/Word/网页多源知识库。

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Next.js     │───▶│  Go 网关      │───▶│  RAG 服务     │
│  前端界面     │    │  认证/限流    │    │  文档索引+检索  │
└──────────────┘    └──────┬───────┘    └──────┬───────┘
                           │                    │
                    ┌──────▼───────┐    ┌──────▼───────┐
                    │  PostgreSQL  │    │  Milvus       │
                    │  元数据/用户  │    │  向量数据库    │
                    └──────────────┘    └──────────────┘
                           │                    │
                    ┌──────▼───────┐    ┌──────▼───────┐
                    │  Redis       │    │  MinIO       │
                    │  缓存/限流    │    │  文档存储     │
                    └──────────────┘    └──────────────┘
```

## 技术栈

| 组件 | 技术 |
|------|------|
| LLM | DeepSeek / Claude / OpenAI（全部 API 接入，不部署本地推理） |
| 嵌入/重排 | BGE-M3 + BGE-Reranker（本地 GPU/CPU 推理） |
| 向量库 | Milvus 2.5（分布式） |
| API 网关 | Go 1.26.3 + Gin |
| RAG 服务 | Python 3.13+ + FastAPI 0.136.3 |
| 前端 | Next.js 16.2 + React 19 + Tailwind CSS 3 |
| 存储 | PostgreSQL 16 + Redis 7 + MinIO |
| 测试 | Vitest（前端 24）+ pytest（后端 75）+ Go test（网关 23） |

## 目录结构

```
ai-qa-system/
├── deploy/infra/              # Docker Compose 编排（PostgreSQL/Redis/Milvus/MinIO）
├── backend/
│   ├── gateway/               # Go API 网关（14 文件, 23 测试）
│   │   └── internal/          #   handler/middleware/config/router
│   └── rag-service/           # Python RAG 服务（23 文件, 75 测试）
│       ├── app/               #   应用逻辑（core/api/llm/retrieval/workers）
│       ├── tests/             #   测试套件
│       └── config/            #   配置管理
├── frontend/ai-qa-app/        # Next.js 前端（12 源文件, 24 测试）
├── docs/                      # 文档目录
│   ├── index.md               #   文档索引
│   ├── deployment-manual.md   #   部署手册
│   └── user-manual.md         #   用户手册
├── ARCHITECTURE.md            # 详细架构设计文档
├── AGENTS.md                  # ← 项目主文档（本文档）
├── CODEBUDDY.md               # WorkBuddy 入口指针
└── README.md                  # GitHub 入口
```

## 项目约束

- **启动路径**：每个服务的启动命令必须在对应子目录下执行（gateway 依赖 `config.yaml` 当前目录，rag-service 依赖相对路径导入）
- **Docker 构建**：context 必须为项目根目录（Dockerfile 使用 `COPY backend/...` 等相对顶层路径）
- **语言**：所有项目代码注释、日志消息、错误信息使用中文
- **API 前缀**：统一为 `/api/v1/`，健康检查为 `/health`
- **独立性**：三个子项目均可独立修改，无跨项目编译依赖

## 启动指南

### 前置条件
- Docker & Docker Compose v2.20+
- Python 3.13+, Node.js 22+, Go 1.26.3+
- （可选）NVIDIA GPU + CUDA 12+ — 用于嵌入/重排序模型加速（可回退到 CPU）

### 配置 LLM
系统通过 API 接入 LLM，**无需本地 GPU 推理**。在 `.env` 中配置：

```bash
# DeepSeek API（推荐）
LLM_API_FORMAT=openai
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-deepseek-api-key
LLM_MODEL=deepseek-chat

# Anthropic Claude
# LLM_API_FORMAT=anthropic
# LLM_PROVIDER=anthropic
# LLM_API_KEY=sk-ant-your-key
# LLM_MODEL=claude-sonnet-4-20250514

# OpenAI
# LLM_API_FORMAT=openai
# LLM_PROVIDER=openai
# LLM_API_KEY=sk-your-openai-key
# LLM_MODEL=gpt-4o
```

> 如需接入内网 vLLM/Ollama 服务器，将 `LLM_BASE_URL` 指向该服务器的 OpenAI 兼容端点即可。

### 启动顺序

```bash
# 1. 基础设施
cd deploy/infra && docker compose up -d

# 2. RAG 服务（gateway 和前端都依赖它）
cd backend/rag-service
pip install -r requirements.txt
python -m app.main                          # → localhost:8001

# 3. API 网关
cd backend/gateway
go mod tidy && go run cmd/main.go           # → localhost:8080

# 4. 前端
cd frontend/ai-qa-app
npm install && npm run dev                  # → localhost:3000
```

Windows 一键启动: `.\deploy\startup.ps1`

### 默认访问

| 服务 | 地址 |
|------|------|
| 前端界面 | http://localhost:3000 |
| API 网关 | http://localhost:8080 |
| RAG 服务 | http://localhost:8001 |
| Milvus 控制台 | http://localhost:9091 |
| MinIO 控制台 | http://localhost:9001 |
| 管理员账号 | admin / admin123 |

## API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/login` | POST | 登录 |
| `/api/v1/auth/register` | POST | 用户注册（需同意隐私政策） |
| `/api/v1/user/logout` | POST | 登出（Token 加入黑名单） |
| `/api/v1/user/profile` | GET | 获取用户信息 |
| `/api/v1/user/export` | GET | 导出个人数据（PIPL §45） |
| `/api/v1/user/delete-request` | POST | 请求删除账号（PIPL §47） |
| `/api/v1/knowledge-bases` | GET/POST | 知识库列表/创建 |
| `/api/v1/knowledge-bases/:kbId/chat` | POST | 流式问答（SSE） |
| `/api/v1/knowledge-bases/:kbId/documents/upload` | POST | 上传文档 |
| `/api/v1/knowledge-bases/:kbId/documents` | GET | 文档列表 |
| `/api/v1/knowledge-bases/:kbId/documents/:docId/status` | GET | 文档索引状态 |
| `/api/v1/admin/stats` | GET | 系统统计 |
| `/api/v1/admin/cleanup` | POST | 触发数据清理 |
| `/health` | GET | 健康检查 |
| `/swagger/*any` | GET | Swagger API 文档（网关） |
| `/docs` / `/redoc` | GET | FastAPI 内置文档（RAG） |

## 测试覆盖

| 项目 | 框架 | 数量 | 覆盖模块 |
|------|------|------|---------|
| Go 网关 | Go test | 23 | config/JWT/熔断器 |
| Python RAG | pytest | 75 | API/Document/RRF/Pipeline/EventBus/Providers |
| Next.js 前端 | Vitest | 24 | auth/api/utils |

```bash
# 前端测试
cd frontend/ai-qa-app && npm run test

# 后端测试
cd backend/rag-service && pip install -r requirements-dev.txt && pytest tests/ -v

# 网关测试
cd backend/gateway && go test ./...
```

> 前/后端测试均可独立运行，不依赖 Docker 基础设施。

## 已交付模块

| 模块 | 文件数 | 核心能力 |
|------|--------|---------|
| **基础设施** | 3 | Docker Compose（Milvus/PostgreSQL/Redis/MinIO）, 数据库 Schema |
| **Go API 网关** | 14 | 路由注册, JWT 认证, 令牌桶限流, 客户端+分布式熔断器, Prometheus 指标, SSE 流式转发, Token 黑名单, 审计日志, 优雅关闭 |
| **Python RAG 服务** | 23 | 文档解析（5 种格式）, 向量化（BGE-M3）, 混合检索（稠密+BM25）, RRF 融合, 重排序, LLM 流式问答 + 双协议（OpenAI/Anthropic）, Redis Streams 事件驱动, OpenTelemetry 追踪, Prometheus 指标 |
| **文档索引 Worker** | 2 | 独立进程消费 Redis Streams, 支持多副本负载均衡, XCLAIM 死信重试 |
| **Next.js 前端** | 12 源文件 | 聊天界面（SSE 流式输出）, 文档上传+轮询, 来源展示, Markdown 渲染, 登录/注册, 暗色模式（light/dark/system）, 数据合规（PIPL 导出/删除）, CSP 安全头 |
| **自定义 Hooks** | 2 | useChat（SSE 流式状态管理）, useDocumentUpload（上传+轮询） |

## 相关文档

- 架构设计: `ARCHITECTURE.md`
- 部署手册: `docs/deployment-manual.md`
- 用户手册: `docs/user-manual.md`
- 子项目详情:
  - `backend/gateway/AGENTS.md`
  - `backend/rag-service/AGENTS.md`
  - `frontend/ai-qa-app/AGENTS.md`
