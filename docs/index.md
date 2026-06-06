# 企业 AI 智能问答系统 — 文档目录

> 本文档目录汇总了项目所有文档的链接和简要说明。

## 📖 核心文档

| 文档 | 说明 | 目标读者 |
|------|------|---------|
| [README.md](../README.md) | 项目简介、快速启动、技术栈概览 | 所有人员 |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | 系统架构、核心流程、技术选型、扩展设计 | 开发者、架构师 |
| [AGENTS.md](../AGENTS.md) | AI Agent 项目概述（启动顺序、约束、测试覆盖） | 开发者、AI Agent |
| [部署手册](./deployment-manual.md) | 环境要求、安装部署、配置指南、运维检查 | 运维、开发者 |
| [用户手册](./user-manual.md) | 功能操作、界面说明、常见问题 | 管理员、终端用户 |

## 📂 技术文档

| 位置 | 说明 |
|------|------|
| [.env.example](../.env.example) | 环境变量模板（含配置说明） |
| [deploy/infra/docker-compose.yml](../deploy/infra/docker-compose.yml) | Docker Compose 编排文件 |
| [deploy/infra/postgres-init.sql](../deploy/infra/postgres-init.sql) | PostgreSQL 数据库初始化脚本 |
| [deploy/startup.ps1](../deploy/startup.ps1) | Windows 一键启动脚本 |
| [deploy/startup.sh](../deploy/startup.sh) | Linux/Mac 一键启动脚本 |

## 🧪 测试

| 位置 | 框架 | 数量 | 说明 |
|------|------|------|------|
| [backend/gateway](../backend/gateway/) | Go test | 23 | config/JWT/熔断器 (handler 和 middleware 未覆盖) |
| [backend/rag-service/tests](../backend/rag-service/tests/) | pytest | 75 | API/Document/RRF/Pipeline/EventBus/Providers |
| [frontend/ai-qa-app/src/test](../frontend/ai-qa-app/src/test/) | Vitest | 24 | auth/api/utils |

## 🧩 核心代码

| 模块 | 路径 | 说明 |
|------|------|------|
| Go API 网关 | `backend/gateway/` | Gin 框架，路由/认证/限流/代理/熔断 |
| RAG 服务 | `backend/rag-service/app/` | FastAPI，RAG 全流程编排 + 事件驱动 |
| 文档索引 Worker | `backend/rag-service/workers/` | Redis Streams 消费者，多副本负载均衡 |
| 前端 | `frontend/ai-qa-app/` | Next.js 16.2 聊天界面 + 认证/主题/数据合规 |

---

## 版本

| 版本 | 日期 | 变更说明 |
|------|------|---------|
| v1.0.0 | 2026-06-05 | 初始文档体系建立。含架构文档、部署手册、用户手册 |
| v1.0.1 | 2026-06-06 | 更新测试覆盖数据、前端认证/暗色模式/数据合规文档 |
