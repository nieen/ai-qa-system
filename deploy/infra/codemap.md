# deploy/infra/

## 职责

基础设施配置。包含 Docker Compose 编排、PostgreSQL 初始化脚本、网关配置和数据库迁移。

## 数据流（Docker Compose）

```
gateway:8080 ←→ postgres:5432 (aiqa_gateway)
gateway:8080 ←→ redis:6379
rag-service:8001 ←→ postgres:5432 (aiqa_rag)
rag-service:8001 ←→ milvus:19530
rag-service:8001 ←→ redis:6379 (Streams + Cache)
rag-service:8001 ←→ minio:9000 (文档存储)
rag-worker → redis:6379 (Streams 消费) → milvus:19530
```

## 依赖启动顺序

1. milvus-etcd → milvus-minio → milvus
2. postgres
3. redis
4. minio
5. rag-migration + gateway-migration
6. rag-service → rag-worker
7. gateway
