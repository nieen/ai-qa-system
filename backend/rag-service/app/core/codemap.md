# backend/rag-service/app/core/

## 职责

核心逻辑层。包含抽象接口、依赖注入容器、Pipeline 编排器、LLM 路由器、嵌入管理、缓存、事件总线等。

## 组件

| 文件 | 职责 |
|------|------|
| `protocols.py` | 抽象接口（ABC）: VectorStore / KeywordStore / EmbeddingModel / Reranker / LLMProvider / QueryPipeline |
| `container.py` | 依赖注入容器，实例模式（非单例），管理所有服务生命周期 |
| `pipeline.py` | NaiveRAGPipeline: 向量化→混合检索→RRF→重排序→上下文构建→LLM 流式生成 |
| `llm_router.py` | LLM 路由器: 主/备模型自动降级 + 自动恢复 |
| `embeddings.py` | BGE-M3 嵌入管理（稠密+稀疏），通过 `run_in_executor` 避免阻塞事件循环 |
| `cache.py` | 对话缓存（Redis + PostgreSQL 双层级） |
| `database.py` | 数据库会话管理（SQLAlchemy async） |
| `circuit_breaker.py` | 熔断器 + 指数退避重试 |
| `event_bus.py` | 应用内事件总线 + Redis Streams 发布 |
| `storage.py` | MinIO 对象存储客户端 |
| `metrics.py` | Prometheus 指标收集 |
| `tracing.py` | OpenTelemetry 链路追踪 |

## 设计

- RRF 融合算法（`rrf_merge`）纯算法实现，不依赖数据库混合检索能力
- 所有外部服务失败静默降级，不抛致命异常
- Container 实例由 lifespan 管理，每个进程独立
