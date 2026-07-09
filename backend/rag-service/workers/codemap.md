# backend/rag-service/workers/

## 职责

独立的 Worker 进程。独立于 RAG API 服务运行，通过 Redis Streams 消费文档索引任务。

## 组件

- `document_worker.py`: 文档索引消费者, 独立入口 `python -m workers.document_worker`
  - 消费 `doc:index` Stream，`doc:workers` 消费者组
  - 支持多副本负载均衡（同 group name 自动分配）
  - 死信重试：Pending Entries + XCLAIM，最多 3 次
- `healthcheck.py`: Worker 健康检查端点
- `metrics.py`: Worker Prometheus 指标
