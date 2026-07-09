# deploy/

## 职责

部署配置目录。包含 Docker 构建文件、Docker Compose 基础设施、数据库迁移脚本和本地部署脚本。

## 组件

- `Dockerfile.gateway`: Go 网关多阶段构建（golang:1.26 → alpine）
- `Dockerfile.rag`: RAG 服务多阶段构建（python:3.14-slim）
- `Dockerfile.migration`: RAG 迁移镜像
- `infra/docker-compose.yml`: 全栈基础设施 — PostgreSQL / Redis / Milvus / MinIO / 网关 / RAG / Worker

## 目录聚合

| 目录 | 职责概要 |
|------|---------|
| `infra/` | Docker Compose + 配置文件 + 迁移脚本 |
