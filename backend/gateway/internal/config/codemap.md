# backend/gateway/internal/config/

## 职责

配置管理。定义 Config 结构体，从 `config.yaml` 加载配置，支持 `JWT_SECRET` / `DATABASE_DSN` / `DB_SSLMODE` 环境变量覆盖。

## 设计

- 所有配置字段通过 yaml tag 绑定
- 加载后设置默认值（端口、超时、熔断阈值等）
- 生产模式强制检测 JWT Secret 是否被覆盖
