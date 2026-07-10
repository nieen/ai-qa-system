# backend/gateway/internal/repository/

## 职责

数据访问接口定义层。定义 UserRepository / AuditRepository / StatsRepository / PIPLRepository 接口，供 Service 层调用。

## 设计

- 接口定义在 `repository.go`，实现分布在 `user_repo.go` / `audit_repo.go` / `stats_repo.go` / `pipl_repo.go`
- `UserRepository`: GetByUsername / GetByID / Create / UpdateLastLogin / ListUsers
- `AuditRepository`: Insert / Query 审计日志
- `StatsRepository`: 系统统计数据
- `PIPLRepository`: 数据合规（导出/删除请求）
