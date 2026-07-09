# deploy/infra/migrations/rag/

## 职责

RAG 服务数据库迁移（`aiqa_rag`）。使用 Alembic 管理的异步迁移。

## 迁移方式

- `alembic.ini`: Alembic 配置（连接到 `aiqa_rag` 数据库）
- `env.py`: Alembic 环境配置（异步引擎 + async session）
- `versions/`: 迁移版本文件（Python 脚本）
