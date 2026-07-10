# backend/gateway/internal/database/

## 职责

PostgreSQL 数据库层。管理全局 `DB *sql.DB` 连接，提供用户 CRUD、审计日志、PIPL 合规（数据导出/删除请求）、数据保留策略清理等方法。

## 设计

- 全局单例 `DB` 变量，启动时通过 `Connect()` 初始化
- 所有操作直接写 SQL，不使用 ORM
- 级联删除用户数据使用事务
- 定时清理任务在 main.go 的 goroutine 中触发
