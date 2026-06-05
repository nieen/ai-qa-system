# 企业 AI 智能问答系统

基于 **LLM + RAG** 的企业级智能问答平台，纯本地私有化部署（不含 LLM 推理），LLM 全部通过 API 接入，支持 DeepSeek / Claude / OpenAI 等供应商，支持 PDF/Word/网页多源知识库。

> 架构设计、技术选型、流程细节详见 [ARCHITECTURE.md](./ARCHITECTURE.md)。
> 部署指南和用户手册详见 [docs/](./docs/) 目录。

## 架构概览

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
| LLM | DeepSeek / Claude / OpenAI (全部 API 接入) |
| 嵌入/重排 | BGE-M3 + BGE-Reranker (本地 GPU/CPU) |
| 向量库 | Milvus 2.5 (分布式) |
| API 网关 | Go 1.26.3 + Gin |
| RAG 服务 | Python 3.13+ + FastAPI |
| 前端 | Next.js 16.2 + Tailwind CSS + React 19 |
| 存储 | PostgreSQL 16 + Redis 7 + MinIO |
| 测试 | Vitest (前端 24) + pytest (后端 75) + Go test (网关 23) |

## 快速开始

> 完整部署说明详见 [部署手册](./docs/deployment-manual.md)。

### 前置条件
- Docker & Docker Compose v2.20+
- Python 3.13+, Node.js 22+, Go 1.26.3+
- （可选）NVIDIA GPU + CUDA 12+ — 用于嵌入/重排序模型的本地加速（可回退到 CPU）

### 1. 启动基础设施
```bash
cd deploy/infra
docker compose up -d
```

### 2. 配置 LLM

系统通过 API 接入 LLM，**无需本地 GPU 推理**。在 `.env` 中配置供应商：

```bash
# DeepSeek API （推荐）
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

> 如需接入本地 vLLM/Ollama 服务器（网络内另一台 GPU 机器），将 `LLM_BASE_URL` 指向该服务器的 OpenAI 兼容端点即可。

### 3. 启动应用服务
```bash
# RAG 服务
cd backend/rag-service
pip install -r requirements.txt
python -m app.main             # → localhost:8001

# API 网关
cd backend/gateway
go mod tidy && go run cmd/main.go   # → localhost:8080

# 前端
cd frontend/ai-qa-app
npm install && npm run dev          # → localhost:3000
```

Windows 可一键启动: `.\deploy\startup.ps1`

## API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/login` | POST | 登录 (admin / admin123) |
| `/api/v1/auth/register` | POST | 用户注册 |
| `/api/v1/user/logout` | POST | 登出 (Token 加入黑名单) |
| `/api/v1/user/profile` | GET | 获取用户信息 |
| `/api/v1/user/export` | GET | 导出个人数据 (PIPL §45) |
| `/api/v1/user/delete-request` | POST | 请求删除账号 (PIPL §47) |
| `/api/v1/knowledge-bases` | GET/POST | 知识库列表/创建 |
| `/api/v1/knowledge-bases/:kbId/chat` | POST | 流式问答 (SSE) |
| `/api/v1/knowledge-bases/:kbId/documents/upload` | POST | 上传文档 |
| `/api/v1/knowledge-bases/:kbId/documents` | GET | 文档列表 |
| `/api/v1/knowledge-bases/:kbId/documents/:docId/status` | GET | 文档索引状态 |
| `/api/v1/admin/stats` | GET | 系统统计 |
| `/health` | GET | 健康检查 |

## 项目结构

```
ai-qa-system/
├── deploy/infra/              # Docker Compose 编排
├── backend/
│   ├── gateway/               # Go API 网关 (8 文件, 23 测试)
│   └── rag-service/           # Python RAG 服务 (23 文件, 75 测试)
│       ├── app/               # 应用代码
│       ├── workers/           # 文档索引 Worker
│       ├── tests/             # 测试套件
│       └── config/            # 配置管理
├── frontend/ai-qa-app/        # Next.js 前端 (15 组件, 24 测试)
├── docs/                      # 文档目录
│   ├── index.md               # 文档索引
│   ├── deployment-manual.md   # 部署手册
│   └── user-manual.md         # 用户手册
├── ARCHITECTURE.md            # 详细架构文档
├── AGENTS.md                  # AI Agent 项目概述
└── README.md
```

## 默认访问

- 前端: http://localhost:3000
- 管理员: admin / admin123

## 测试

```bash
# 前端测试
cd frontend/ai-qa-app && npm run test

# 后端测试
cd backend/rag-service && pip install -r requirements-dev.txt && pytest tests/ -v

# 网关测试
cd backend/gateway && go test ./...
```

## License
MIT
