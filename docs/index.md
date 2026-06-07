# 企业 AI 智能问答系统 — 文档目录

> 项目文档的导航页，按目标读者分类。

## 📖 项目概览

| 文档 | 说明 |
|------|------|
| [README.md](../README.md) | 项目首页——功能简介、快速启动、技术栈 |

## 🏗️ 架构与开发

| 文档 | 说明 | 目标读者 |
|------|------|---------|
| [ARCHITECTURE.md](../ARCHITECTURE.md) | 系统架构、RAG 核心流程、技术选型详解 | 架构师、开发者 |
| [AGENTS.md](../AGENTS.md) | AI Agent 工作标准——项目约束、代码约定 | 开发者、AI Agent |
| [ROADMAP.md](../ROADMAP.md) | 项目发展规划——Phase 2/3/4 路线图 | 开发者、项目管理者 |

## 🚀 部署与运维

| 文档 | 说明 |
|------|------|
| [部署手册](./deployment-manual.md) | 环境要求、安装部署、配置指南、运维检查清单 |

## 👤 用户指南

| 文档 | 说明 |
|------|------|
| [用户手册](./user-manual.md) | 系统登录、知识库管理、文档上传、智能问答、常见问题 |

## 📂 参考资料

| 位置 | 说明 |
|------|------|
| [.env.example](../.env.example) | 环境变量模板（含完整配置说明和注释） |
| [deploy/infra/docker-compose.yml](../deploy/infra/docker-compose.yml) | Docker Compose 编排（PostgreSQL / Redis / Milvus / MinIO） |
| [deploy/infra/postgres-init.sql](../deploy/infra/postgres-init.sql) | PostgreSQL Schema 初始化脚本 |
| [deploy/startup.ps1](../deploy/startup.ps1) | Windows 一键启动脚本 |
| [deploy/startup.sh](../deploy/startup.sh) | Linux/Mac 一键启动脚本 |

---

> 文档版本: v1.0.2 | 更新日期: 2026-06-07
