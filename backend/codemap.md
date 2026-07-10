# backend/

## 职责

后端代码根目录，包含两个独立子项目：Go API 网关和 Python RAG 服务。两者无跨项目编译依赖，共享同一 PostgreSQL 实例的不同数据库。

## 目录聚合

| 目录 | 职责概要 |
|------|---------|
| `gateway/` | Go API 网关 — BFF 模式，认证/限流/熔断/请求代理 |
| `rag-service/` | Python RAG 服务 — 文档索引/向量检索/LLM 问答 |
