# backend/gateway/cmd/migrate/

## 职责

数据库迁移 CLI 工具。统一管理网关（golang-migrate）和 RAG（Alembic）两个数据库的 schema 迁移。

## 设计

- 通过 Docker 容器执行 golang-migrate 迁移网关 schema
- 通过子进程执行 alembic 迁移 RAG schema
- 支持 `up` / `down` / `status` / `new` 四个子命令
