# AGENTS.md — 企业 AI 智能问答系统

基于 **LLM + RAG** 的企业级知识库问答平台，LLM 全部通过 API 接入，支持 DeepSeek / Claude / OpenAI。

## 项目约束

- **启动路径**：每个服务的启动命令必须在对应子目录下执行（gateway 依赖 `config.yaml` 当前目录，rag-service 依赖相对路径导入）
- **Docker 构建**：context 必须为项目根目录（Dockerfile 使用 `COPY backend/...` 等相对顶层路径）
- **语言**：所有代码注释、日志消息、错误信息使用中文
- **API 前缀**：统一为 `/api/v1/`，健康检查为 `/health`
- **独立性**：三个子项目均可独立修改，无跨项目编译依赖

## 数据库

- PostgreSQL Schema 在 `deploy/infra/postgres-init.sql`，代码不直接操作 DDL
- Schema 由网关和 RAG 服务共享（同一实例，不同表）

## 子项目入口

| 子项目 | 路径 | 语言 | 入口文件 |
|--------|------|------|---------|
| API 网关 | `backend/gateway/AGENTS.md` | Go 1.26.3 + Gin | `cmd/main.go` |
| RAG 服务 | `backend/rag-service/AGENTS.md` | Python 3.13+ + FastAPI | `app/main.py` |
| 前端 | `frontend/ai-qa-app/AGENTS.md` | Next.js 16.2 + React 19 | `src/app/page.tsx` |
