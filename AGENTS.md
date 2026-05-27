# AGENTS.md — AI 智能问答系统

## 项目概述

企业级 RAG 智能问答平台，三个独立服务 + 基础设施：

```
frontend/ai-qa-app/     → Next.js 14 (端口 3000)
backend/gateway/        → Go + Gin API 网关 (端口 8080)
backend/rag-service/    → Python + FastAPI RAG 服务 (端口 8001)
deploy/infra/           → Docker Compose (PostgreSQL/Redis/Milvus/MinIO)
```

每个子项目有各自的 `AGENTS.md`，写代码前务必先读对应文件。

## 启动顺序

必须先启动基础设施，然后按依赖顺序启动服务：

```bash
# 1. 基础设施
cd deploy/infra && docker compose up -d

# 2. RAG 服务 (gateway 和前端都依赖它)
cd backend/rag-service && pip install -r requirements.txt && python -m app.main

# 3. API 网关
cd backend/gateway && go mod tidy && go run cmd/main.go

# 4. 前端
cd frontend/ai-qa-app && npm install && npm run dev
```

Windows 可一键启动: `.\deploy\startup.ps1`

## 项目约束

- **每个服务的启动命令必须在对应子目录下执行** -- gateway 依赖 `config.yaml` 在当前目录，rag-service 依赖相对路径导入
- Docker 构建时 context 必须为项目根目录（Dockerfile 使用 `COPY backend/...` 等相对顶层路径）
- 所有项目代码注释、日志消息、错误信息使用中文
- API 前缀统一为 `/api/v1/`，健康检查为 `/health`
- 三个子项目均可独立修改，无跨项目编译依赖

## 环境变量

根目录 `.env.example` 包含所有服务共用的配置模板，复制为 `.env` 后各服务自行读取。
重点：LLM 主/备模型、数据库连接、JWT secret 需要按环境配置。

## 相关文档

- 架构设计: `ARCHITECTURE.md`
- 项目全景: `overview.md`
