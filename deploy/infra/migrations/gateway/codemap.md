# deploy/infra/migrations/gateway/

## 职责

Go 网关数据库迁移（`aiqa_gateway`）。使用 golang-migrate 格式的 SQL 迁移文件。

## 当前迁移

- `000001_initial.up.sql`: 初始 schema — users / conversations / messages / documents / knowledge_bases / audit_logs / user_consents / deletion_requests 表
