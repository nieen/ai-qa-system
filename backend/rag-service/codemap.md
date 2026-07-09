# backend/rag-service/

## 职责

Python RAG 服务（FastAPI），提供文档索引、向量检索、LLM 问答等核心 RAG 能力。所有 LLM 通过 HTTP API 接入，嵌入模型和重排模型在本地运行。

## 架构

面向接口 + 依赖注入 + Pipeline 编排。所有外部依赖通过抽象接口（`protocols.py`）隔离，Container 管理生命周期。

## 数据流

```
API 请求 → routes.py → Pipeline.execute() → 向量化 → 混合检索 → RRF 融合 → 重排序 → LLM 流式生成
                                                      ├─ Milvus (向量)
                                                      └─ BM25 (关键词)
```

## 目录聚合

| 目录 | 职责概要 |
|------|---------|
| `app/api/` | FastAPI 路由 — 请求解析和响应序列化 |
| `app/core/` | 核心层 — 协议接口/容器/Pipeline/LLM/嵌入/缓存/事件总线 |
| `app/ingestion/` | 文档处理 — 解析/清洗/分块 |
| `app/llm/` | LLM 提供商实现 — OpenAI 兼容 / Anthropic |
| `app/retrieval/` | 检索层 — Milvus 客户端 / 重排序 |
| `config/` | 配置管理— Pydantic Settings |
| `workers/` | 独立 Worker 进程 — Redis Streams 文档索引消费者 |
