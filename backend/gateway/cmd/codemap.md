# backend/gateway/cmd/

## 职责

Go 入口点目录。包含两个 main 包：`cmd/main.go`（API 网关服务）和 `cmd/migrate/main.go`（数据库迁移工具）。

## 设计

- `main.go`: 加载配置 → 初始化 Logger/Redis/DB → 设置中间件链 → 注册路由 → 启动 HTTP 服务器 → 等待优雅关闭信号
- `migrate/main.go`: 统一迁移入口，通过 Docker 运行 golang-migrate（网关 schema）+ 子进程运行 Alembic（RAG schema）
