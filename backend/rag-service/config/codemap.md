# backend/rag-service/config/

## 职责

配置管理。基于 Pydantic Settings，支持环境变量 > `.env` 文件 > 默认值三级优先级。

## 设计

- `settings.py`: 定义所有配置项（LLM 端点/API Key/嵌入模型/Milvus/Redis/MinIO/Pipeline 等）
- 配置前缀 `APP_` / `LLM_` / `MILVUS_` / `REDIS_` 等
