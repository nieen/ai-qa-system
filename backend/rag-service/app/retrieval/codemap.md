# backend/rag-service/app/retrieval/

## 职责

检索层。封装 Milvus 向量数据库客户端和 BM25 关键词检索、Reranker 重排序服务。

## 组件

- `milvus_client.py`: MilvusClient（向量检索）+ MilvusKeywordStore（BM25 关键词检索），带重试机制（指数退避 3 次）
- `reranker.py`: 重排序服务，对 RRF 融合结果做精排
