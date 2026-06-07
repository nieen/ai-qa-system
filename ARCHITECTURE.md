# 架构设计文档

> 本文档详细描述企业 AI 智能问答系统的技术架构、核心流程和关键技术选型。
> 快速上手请参阅 [README.md](./README.md)。

---

## 目录

- [1. 系统架构总览](#1-系统架构总览)
- [2. RAG 核心流程](#2-rag-核心流程)
  - [2.1 索引流程](#21-索引流程-ingestion-pipeline)
  - [2.2 分块策略](#22-分块策略-chunking-strategy)
  - [2.3 查询流程](#23-查询流程-query-pipeline)
  - [2.4 检索召回：两路并行 + RRF 融合 + 精排](#24-检索召回两路并行--rrf-融合--精排)
- [3. 关键技术选型](#3-关键技术选型)
  - [3.1 向量数据库：Milvus](#31-向量数据库milvus-v254)
  - [3.2 嵌入模型：BGE-M3](#32-嵌入模型bge-m3)
  - [3.3 重排序模型：BGE-Reranker](#33-重排序模型bge-reranker-v2-m3)
  - [3.4 LLM API 接入](#34-llm-api-接入)
- [4. 硬件配置建议](#4-硬件配置建议)
- [5. 知识库数据模型](#5-知识库数据模型)
- [6. Prompt 模板设计](#6-prompt-模板设计)
- [7. 安全与审计](#7-安全与审计)
- [8. 监控指标](#8-监控指标)
- [9. 代码架构与扩展性设计](#9-代码架构与扩展性设计)
  - [9.1 接口抽象层](#91-核心抽象接口层-protocols)
  - [9.2 依赖注入容器](#92-依赖注入容器-container)
  - [9.3 LLM 双协议路由与降级](#93-llm-双协议路由与降级)
  - [9.4 Pipeline 编排器](#94-pipeline-编排器)
  - [9.5 熔断与重试](#95-熔断与重试)
  - [9.6 持久化缓存](#96-持久化缓存)
  - [9.7 配置中心](#97-配置中心)
  - [9.8 Phase 2/3 扩展路径](#98-phase-23-扩展路径)

---

## 1. 系统架构总览

### 5 层架构

```
┌──────────────────────────────────────────────────────────────────┐
│                  用户交互层 (Frontend)                             │
│       Next.js 16 Web App + 企业微信/飞书 Bot                      │
└────────────────────┬─────────────────────────────────────────────┘
                     │ HTTP/WebSocket / SSE
┌────────────────────▼─────────────────────────────────────────────┐
│                API 网关层 (Go + Gin)                                │
│                                                                   │
│  ┌─────────────────────────────┐  ┌────────────────────────────┐  │
│  │  直连 PostgreSQL            │  │  代理到 RAG 服务           │  │
│  │  · 认证 (Login/Register/JWT)│  │  · 知识库 CRUD             │  │
│  │  · 用户管理 / 角色管理       │  │  · 文档管理 / 上传         │  │
│  │  · 审计日志                 │  │  · 问答 / 对话             │  │
│  │  · PIPL 合规                │  │  · 流式 SSE 输出           │  │
│  └─────────────────────────────┘  └────────────────────────────┘  │
│                                                                   │
│  限流熔断 | JWT 鉴权 | 请求路由 | RequestID 链路追踪                │
└────────────────────┬─────────────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────────────┐
│                    RAG 服务层 (Python + FastAPI)                    │
│                                                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────┐ │
│  │  问答编排       │  │  文档处理       │  │  后台 Worker         │ │
│  │  · 查询预处理   │  │  · 文档解析     │  │  · 文档索引 (MQ 消费)│ │
│  │  · 混合检索     │  │  · 文本清洗     │  │  · 事件驱动 Pipeline │ │
│  │  · RRF 融合     │  │  · 分块     │  │                     │ │
│  │  · 精排重排序   │  │  · 元数据提取   │  │                     │ │
│  │  · 上下文组装   │  │                │  │                     │ │
│  │  · LLM 生成     │  │                │  │                     │ │
│  └────────────────┘  └────────────────┘  └──────────────────────┘ │
└──────┬──────────────────────┬────────────────────────────────────┘
       │                      │
┌──────▼──────────────────────▼────────────────────────────────────┐
│                     AI 引擎层                                      │
│  ┌────────────────┐ ┌──────────────┐ ┌───────────────────┐       │
│  │  LLM API       │ │ Embedding    │ │ Reranker          │       │
│  │  (DeepSeek/    │ │ (BGE-M3)     │ │ (BGE-Reranker)    │       │
│  │   Claude/      │ │              │ │                   │       │
│  │   OpenAI)      │ │              │ │                   │       │
│  └────────────────┘ └──────────────┘ └───────────────────┘       │
└──────┬──────────────────────┬────────────────────────────────────┘
       │                      │
┌──────▼──────────────────────▼────────────────────────────────────┐
│                      数据存储层                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐          │
│  │ Milvus   │ │PostgreSQL│ │ Redis    │ │ MinIO      │          │
│  │(向量库)  │ │(用户/审计/│ │(限流/    │ │(文档存储)   │          │
│  │          │ │ 对话/文档)│ │ Streams) │ │            │          │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘          │
└──────────────────────────────────────────────────────────────────┘
```

### 技术栈一览

| 层 | 组件 | 技术 | 版本/说明 |
|----|------|------|----------|
| **LLM** | 供应商 | DeepSeek / Claude / OpenAI (API 接入) | 全部通过 API，不部署本地推理模型 |
| | 备用模型 | 自动降级 (主模型不可用时切换) | 支持不同供应商交叉备用 |
| | 双协议 | OpenAI 兼容格式 + Anthropic Messages | 覆盖主流 LLM 供应商 |
| **嵌入** | Embedding | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | 1024 维，稠密+稀疏+ColBERT 三通道 |
| | Reranker | [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | 精排提升 15-25% |
| **向量库** | 向量数据库 | [Milvus v2.5.4](https://milvus.io/) | 企业级分布式，原生 hybrid_search |
| **文档处理** | 文档解析 | [unstructured.io](https://unstructured.io/) + Marker | PDF/Word/HTML 解析 |
| | 分块 | 混合策略 (标题分割 + tiktoken 固定窗口) | CHUNK_SIZE=512, OVERLAP=64 |
| **后端** | API 网关 | Go + [Gin](https://gin-gonic.com/) | 高并发，低延迟；直连 PostgreSQL 处理认证/用户/审计，代理 RAG |
| | RAG 编排 | Python + [FastAPI](https://fastapi.tiangolo.com/) | 问答编排 + 文档处理 + Worker 后台消费 |
| **前端** | Web 界面 | [Next.js 16](https://nextjs.org/) | SSR, 流式输出, Tailwind, React 19 |
| **存储** | 元数据 | PostgreSQL 16 | 用户/知识库/对话 |
| | 缓存 | Redis 7 | 会话/限流 |
| | 对象存储 | MinIO | 原始文档，S3 兼容 |

---

## 2. RAG 核心流程

### 2.1 索引流程 (Ingestion Pipeline)

```
原始文档 (PDF / Word / 网页 / API 数据)
        │
        ▼
┌──────────────────────┐
│ 文档解析              │ ← Unstructured.io: 提取文本/表格/图片
│ 清洗与标准化           │ ← 中文 OCR 校正，编码统一为 UTF-8
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 分块策略              │ ← 混合策略 (详见 2.2 节)
│ - 按 Markdown 标题     │
│ - 固定窗口 + 重叠      │
│ - 小段落合并           │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 向量化 + 元数据        │ ← BGE-M3 生成 1024 维稠密向量
│ 存储到 Milvus         │ ← 同时存文本块、文档来源、层级路径
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 关键词索引 (BM25)      │ ← Milvus 内置 BM25 索引
│ 准备混合检索           │ ← 构建 inverted index
└──────────────────────┘
```

### 2.2 分块策略 (Chunking Strategy)

**代码位置**: `backend/rag-service/app/ingestion/document_processor.py` → `_chunk_text()`

采用三层混合策略，按优先级依次尝试：

```
                  原始文本
                      │
            ┌─────────▼─────────┐
            │  按 Markdown 标题   │
            │  尝试分割段落        │
            └──────┬──────┬─────┘
                   │      │
              命中标题    未命中标题
                   │      │
         ┌─────────▼      ▼──────────┐
         │ 按标题分段后      │  固定窗口分块  │
         │ 再固定窗口分块    │               │
         └────────────────────────────┘
                      │
            ┌─────────▼─────────┐
            │  小段落合并         │
            │  < 256 tokens 碎片 │
            │  自动向前合并       │
            └───────────────────┘
```

#### 参数配置

| 参数 | 路径 | 默认值 | 说明 |
|------|------|--------|------|
| `CHUNK_SIZE` | `config/settings.py` | 512 tokens | 每个分块的目标大小 |
| `CHUNK_OVERLAP` | `config/settings.py` | 64 tokens | 相邻分块重叠 (12.5%) |
| `EMBEDDING_MAX_LENGTH` | `config/settings.py` | 512 | BGE-M3 最大输入长度 |

#### Token 计数

使用 **tiktoken** (OpenAI `cl100k_base` 编码) 精确计算 token 数，中文场景下 512 tokens ≈ 350-400 字。

#### 核心实现

```python
# 优先按 Markdown 标题分割 (结构化文档)
sections = self._split_by_headings(text)
if len(sections) > 1:
    for heading, content in sections:
        sub_chunks = self._fixed_size_chunks(content)
        chunks.extend(sub_chunks)
else:
    # 非结构化文档: 固定窗口
    chunks = self._fixed_size_chunks(text)

# 固定窗口分块 (tiktoken 编码)
def _fixed_size_chunks(self, text):
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunks.append(enc.decode(tokens[start:end]))
        start += chunk_size - overlap
```

### 2.3 查询流程 (Query Pipeline)

```
用户提问
   │
   ▼
┌──────────────┐
│ 查询预处理     │ ← 查询改写 (Query Rewrite)
│  - 意图识别    │     历史上下文补全 → 独立自包含问题
│  - 查询扩展    │ ← 同义词扩展 / HyDE
└──────┬───────┘
       ▼
┌──────────────┐
│ 混合检索      │ ← 两路并行 (详见 2.4 节)
│ 稠密语义+BM25  │
└──────┬───────┘
       ▼
┌──────────────┐
│ RRF 融合排序   │ ← Reciprocal Rank Fusion
│ top-30        │     对三路排名做加权合并
└──────┬───────┘
       ▼
┌──────────────┐
│ 精排重排序     │ ← BGE-Reranker 逐对打分
│ top-30→top-5  │     保留最相关的 3-5 条
└──────┬───────┘
       ▼
┌──────────────┐
│ 上下文组装     │ ← System Prompt + Context + History + Question
│              │     强制要求引用来源、无法回答时明确告知
└──────┬───────┘
       ▼
┌──────────────┐
│ LLM 生成回答   │ ← DeepSeek / Claude (API 流式 SSE 输出)
│  流式输出      │     打字机效果 + 来源标注
└──────┬───────┘
       ▼
┌──────────────┐
│ 后处理        │ ← 来源标注、引用验证、Markdown 格式化
└──────────────┘
```

### 2.4 检索召回：两路并行 + RRF 融合 + 精排 (解耦设计)

**核心原则**: 向量检索和关键词检索是**两个独立的服务**，在 Pipeline 层用纯算法 (RRF) 融合结果。

```
                     用户查询
                         │
                 ┌───────▼───────┐
                 │  BGE-M3 编码   │
                 └───┬───────────┘
                     │
           ┌─────────┘
           ▼                     ▼
    ┌──────────────┐    ┌──────────────┐
    │ VectorStore   │    │ KeywordStore  │
    │ 向量检索      │    │ 关键词检索    │
    │ (纯向量,      │    │ (独立于向量库) │
    │  top_k=30)   │    │  top_k=30    │
    │              │    │              │
    │ MilvusStore  │    │ MilvusBM25   │
    │ PGVectorStore│    │ PGFTSStore   │
    │ QdrantStore  │    │ SimpleBM25   │
    └──────┬───────┘    └──────┬───────┘
           │                  │
           └────────┬─────────┘
                    ▼
           ┌────────────────┐
           │ RRF 融合 (纯算法) │ ← Reciprocal Rank Fusion
           │ top_k=30       │    不依赖任何数据库的内置能力
           └───────┬────────┘
                   ▼
           ┌────────────────┐
           │ BGE-Reranker   │ ← 逐对计算 query-doc 相关性
           │ top_30→top_5   │
           └───────┬────────┘
                   ▼
              ┌────────┐
              │ LLM 生成│ ← 最终 5 条 + 引用标记
              └────────┘
```

#### 为什么解耦

| 方案 | 问题 |
|------|------|
| ❌ 依赖单个数据库的混合检索 | PGVector(无BM25)、Chroma(无BM25) 无法工作 |
| ❌ 只用向量检索 | 丢失精确关键词匹配能力（数字、代码、专有名词） |
| ✅ VectorStore + KeywordStore 独立 | 任何向量库都能搭配任何关键词引擎 |

#### 接口设计

```python
class VectorStore(ABC):
    """只做向量相似度搜索"""
    async def similarity_search(query_vector, top_k) -> List[RetrievedChunk]

class KeywordStore(ABC):
    """只做关键词/全文检索"""
    async def keyword_search(query_text, top_k) -> List[RetrievedChunk]
```

#### 内置实现

| 接口 | 实现 | 技术栈 |
|------|------|--------|
| `VectorStore` | `MilvusClient` | Milvus IVF_FLAT |
| `VectorStore` | `PGVectorStore` (参考) | PostgreSQL + pgvector |
| `KeywordStore` | `MilvusKeywordStore` | Milvus 内置 BM25 (sparse 字段) |
| `KeywordStore` | `PGFTSStore` (参考) | PostgreSQL tsvector 全文检索 |
| `KeywordStore` | `SimpleBM25Store` (参考) | 内存 BM25 (无需额外服务) |

#### RRF 融合算法 (纯 Python)

```python
def rrf_merge(vector_results, keyword_results, k=60, top_k=30):
    """Reciprocal Rank Fusion — 不依赖任何数据库"""
    scores = {}
    for rank, doc in enumerate(vector_results):
        scores[key(doc)] = 1.0 / (k + rank + 1)
    for rank, doc in enumerate(keyword_results):
        key = doc.chunk_id or doc.content[:100]
        if key in scores:
            scores[key] += 1.0 / (k + rank + 1)
        else:
            scores[key] = 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
```

#### 配置切换

```bash
# 使用 Milvus 做向量 + Milvus BM25 做关键词
VECTOR_STORE_TYPE=milvus
KEYWORD_STORE_TYPE=milvus

# 切换为 PGVector + PostgreSQL FTS
VECTOR_STORE_TYPE=pgvector
KEYWORD_STORE_TYPE=pgvector
```

#### 两路检索的互补作用

| 检索路 | 原理 | 擅长 | 盲区 |
|--------|------|------|------|
| **稠密向量** | BGE-M3 语义编码，余弦相似度 (IP) | "如何配置数据库" → 找到"修改 postgres dsn 参数" | 精确关键词、罕见词 |
| **BM25 关键词** | 词频-逆文档频率 (Milvus 内置) | 搜"Milvus 端口 19530" 直接命中精确数字 | 同义词、语义泛化 |

> 注意: BGE-M3 还支持 `encode_lexical` 生成稀疏向量，但当前 Pipeline 未启用该路。BM25 已在关键词检索层覆盖了稀疏检索的需求。`embed_sparse()` 方法保留作为未来"三路检索"扩展点。

#### 为什么两路并行效果好于单路

- 如果只用稠密向量：搜"端口号"找不到"19530"（数字不在语义空间里）
- 如果只用 BM25：搜"计算机连不上"找不到"连接异常"（不同表述）
- **两路互补 + RRF 融合 + Reranker 精排**，召回精度比纯向量检索高 **20-30%**

#### 核心代码

```python
# 1. 稠密向量检索请求
dense_req = AnnSearchRequest(
    data=[query_vector],
    anns_field="embedding",
    param={"metric_type": "IP", "params": {"nprobe": 16}},
    limit=30,  # RETRIEVAL_TOP_K_VECTOR
)

# 2. Milvus hybrid_search 自动处理 BM25 + 向量融合
results = collection.hybrid_search(
    reqs=[dense_req],
    rerank=RRFRanker(),   # RRF 融合排序
    limit=top_k,
)

# 3. BGE-Reranker 精排
reranked = reranker_service.rerank(
    query=question,
    documents=results,
    top_k=5,     # RETRIEVAL_FINAL_TOP_K
)
```

#### 检索参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `RETRIEVAL_TOP_K_VECTOR` | 30 | 稠密检索召回数量 |
| `RETRIEVAL_TOP_K_BM25` | 30 | BM25 检索召回数量 |
| `RETRIEVAL_FINAL_TOP_K` | 5 | 最终送给 LLM 的文档数 |
| `RETRIEVAL_SCORE_THRESHOLD` | 0.3 | 最低分数阈值 |

---

### 2.5 上下文管理：分层压缩策略

**代码位置**: `app/llm/llm_service.py` → `_compress_history()` + `_build_messages()`

#### 背景问题

用户连续多轮对话时，全部历史消息塞入 LLM 会导致：
- **Token 浪费**：前几轮的对话信息密度低，占据大量上下文窗口
- **注意力稀释**：长上下文中，LLM 对最近问题的关注度下降
- **Token 超限**：超过 LLM 的 max_tokens 限制

#### 分层策略

```
短对话 (≤ 6 轮)                       长对话 (> 6 轮)
┌─────────────────────┐              ┌──────────────────────────┐
│ 所有轮次原样传递       │              │ [历史摘要] ← LLM 压缩     │
│                     │              │ 近期 {1,2,3,4,5,6} 轮     │
│                     │              │ [原样] ← 最近 2 轮        │
│ 轮1, 2, 3, 4, 5, 6  │              │                          │
│ (全部)               │              │ 轮1~4 → 摘要 (50-100字)  │
└─────────────────────┘              │ 轮5~6 → 原样保留         │
                                      └──────────────────────────┘
```

#### 实现细节

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `MAX_VERBATIM_ROUNDS` | 6 条 | 超过此条数触发压缩 |
| `KEEP_RECENT_ROUNDS` | 2 轮 | 保留的最近完整轮次 |

**压缩触发器**: `_compress_history()`

```python
async def _compress_history(self, history):
    # 短对话不压缩
    if len(history) <= MAX_VERBATIM_ROUNDS * 2:
        return ""

    # 分离旧轮次和近轮次
    keep_count = KEEP_RECENT_ROUNDS * 2
    old_history = history[:-keep_count]

    # 调用 LLM 将旧轮次压缩为 50-100 字摘要
    summary = await self.chat(
        question=HISTORY_SUMMARY_PROMPT.format(history_text=old),
        context=[], history=[],
    )
    return summary
```

**消息组装**: `_build_messages()`

```
System Prompt (含历史摘要 + 最近轮次文本)
    ↓
最近 2 轮消息 (作为 chat messages 原样传递，保留对话语气)
    ↓
当前用户问题
```

#### 摘要 Prompt

```text
请将以下对话中已经解决的问题和关键信息总结为一段话（50-100字），
只包含事实性信息，不包含客套话。

目标是：后续 AI 能够基于此摘要理解对话背景，
无需再阅读完整的原始对话。
```

#### 兜底策略

如果 LLM 摘要生成失败（网络超时等），`_compress_history` 返回空字符串，
`_build_messages` 自动回退到简单的截断策略（保留最近 6 条），
不影响正常对话流程。

---

## 3. 关键技术选型

### 3.1 向量数据库：Milvus v2.5.4

| 维度 | 选择 | 原因 |
|------|------|------|
| **数据库** | Milvus 2.5.4 | 企业级分布式，原生 hybrid_search API |
| **部署方式** | Docker Compose (Milvus + ETCD + MinIO) | 三组件一体部署，生产可拆独立集群 |
| **索引 (稠密)** | IVF_FLAT, nlist=1024 | 平衡准确率和检索速度 |
| **索引 (稀疏)** | SPARSE_INVERTED_INDEX | BGE-M3 稀疏向量专用格式 |
| **距离度量** | IP (内积) | L2 归一化向量配合 = 余弦相似度 |
| **GPU 加速** | 支持 (已预留 GPU) | `KNOWHERE_GPU_RESOURCE_ENABLE=true` |
| **HTTP 端口** | 9091 | 管理控制台 |
| **gRPC 端口** | 19530 | 客户端通信 |

**为什么选 Milvus 而不是其他：**

| 竞品 | Milvus 优势 |
|------|------------|
| **Qdrant** | 单节点性能好但分布式弱于 Milvus；100+ 用户需分布式扩展 |
| **Pinecone** | 托管服务，数据不能出网，不符合本地部署要求 |
| **Elasticsearch** | 需要额外搭 ES + 向量插件两套系统，无原生 hybrid_search |

**Milvus 的核心优势：**
- 原生混合检索：不需要额外搭 Elasticsearch，Milvus 内置 BM25 + 向量检索的 hybrid_search API
- GPU 索引构建：相比纯 CPU 方案索引速度快 10x+
- 百亿级扩展：通过分片和副本水平扩展，适合企业 100+ 用户场景
- 生态成熟：与 LlamaIndex / LangChain 都有官方集成

### 3.2 嵌入模型：BGE-M3

- **模型**: [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)
- **向量维度**: 1024
- **特点**: 支持稠密向量 + 稀疏向量 + ColBERT 三通道编码
- **国产化**: 北京智源研究院出品，中文语料训练，效果好于同尺寸英文模型
- **部署**: sentence-transformers，可 GPU 批量编码

### 3.3 重排序模型：BGE-Reranker v2-m3

- **模型**: [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- **功能**: 对检索结果逐对计算 query-doc 相关性分数
- **效果**: top-30 精排到 top-5，准确率提升 15-25%
- **部署**: transformers，推荐 GPU 推理

### 3.4 LLM API 接入

系统通过标准 API 接入 LLM，**不部署本地推理模型**。支持多供应商、双协议、自动降级。

| 维度 | 说明 |
|------|------|
| **接入方式** | 全部通过 HTTP API，无需本地 GPU |
| **协议支持** | OpenAI 兼容格式 (`/v1/chat/completions`) + Anthropic Messages (`/v1/messages`) |
| **供应商** | DeepSeek (推荐)、Claude、OpenAI 等 |
| **备用模型** | 主模型不可用时自动切换，支持不同供应商交叉备用 |
| **网络需求** | 需访问对应 API 端点（内网部署 vLLM 服务器也可通过 `LLM_BASE_URL` 指向） |

> **注意**: 嵌入模型 (BGE-M3) 和重排序模型 (BGE-Reranker) 仍在本地运行，需要 GPU 加速（可回退 CPU）。

---

## 4. 硬件配置建议

LLM 全部通过 API 接入，**不消耗本地 GPU 资源**。GPU 仅用于嵌入模型 (BGE-M3) 和重排序模型 (BGE-Reranker) 的本地推理。

| 规模 | 推荐配置 | GPU | 说明 |
|------|---------|-----|------|
| **入门** (10-30人) | 16 核 CPU + 64GB RAM | 可选 1× RTX 4090 | 嵌入/重排可回退 CPU |
| **标准** (30-100人) | 32 核 CPU + 128GB RAM | 1× RTX 4090 24G | GPU 加速嵌入/重排 |
| **大型** (100-500人) | 64 核 CPU + 256GB RAM | 2× RTX 4090 | 高吞吐嵌入/重排 |

**存储**:
- **应用数据**: 500GB+ NVMe SSD (Milvus + PostgreSQL + MinIO)
- **网络**: 1GbE 内网 (LLM API 需出网或可访问内网 API 端点)

---

## 5. 知识库数据模型

### 数据库 Schema (PostgreSQL)

详见 `deploy/infra/postgres-init.sql`，核心表及**数据归属**：

| 表 | 归属 | 说明 | 关键字段 |
|----|------|------|---------|
| **users** | **网关** (Go) | 认证、用户管理、角色 | `id, username, password_hash, role, is_active` |
| **audit_logs** | **网关** (Go) | 审计日志（写操作自动记录） | `id, user_id, action, resource_type, details, ip_address` |
| **user_consents** | **网关** (Go) | PIPL 同意记录 | `id, user_id, consent_type, consent_version, granted_at` |
| **deletion_requests** | **网关** (Go) | PIPL 删除请求（7 天冷静期） | `id, user_id, status, expires_at` |
| **knowledge_bases** | **RAG** (Python) | 知识库元数据 | `id, name, owner_id, embedding_model, chunk_size` |
| **documents** | **RAG** (Python) | 文档元数据，MinIO 存储原文 | `id, knowledge_base_id, title, file_type, status, checksum` |
| **document_chunks** | **RAG** (Python) | 文档块元数据 | `id, document_id, chunk_index, content, milvus_id` |
| **conversations** | **RAG** (Python) | 对话历史 | `id, user_id, knowledge_base_id, title, message_count` |
| **messages** | **RAG** (Python) | 对话消息 | `id, conversation_id, role, content, sources` |
| organizations | 预留 | 组织（目前未使用） | |

> **⚠️ 数据访问边界**:
> - 网关仅连接 `aiqa_gateway` 数据库，**只应读写** `users`、`audit_logs`、`user_consents`、`deletion_requests`
> - RAG 服务仅连接 `aiqa_rag` 数据库，**只应读写** `knowledge_bases`、`documents`、`document_chunks`、`conversations`、`messages`
> - 网关需要知识库/文档等统计信息时，**通过 RAG API 代理获取**（`/admin/stats`），而非直接读表
> - RAG 服务需要用户信息时，通过网关 API 的 `X-User-ID` / `X-User-Role` 请求头透传，不直读 `users` 表
> - RAG 表不再设跨库外键（`owner_id`、`created_by`、`user_id` 列为普通 VARCHAR），业务完整性由 API 保证
> - 两个库可在同一 PostgreSQL 实例（不同 database name），也可各自独立实例
> - Schema 归各自服务所有，演化时由对应服务管理 migration

### 数据库版本管理

**RAG 服务 (`aiqa_rag`)** 使用 **Alembic** (Python) 管理：

```
deploy/infra/migrations/rag/
├── alembic.ini
├── env.py
└── versions/
    └── 2026_01_01_baseline.py
```

```bash
alembic -c deploy/infra/migrations/rag/alembic.ini upgrade head
```

**网关 (`aiqa_gateway`)** 使用 **golang-migrate** (Go 生态) 管理：

```
deploy/infra/migrations/gateway/
├── 000001_initial.up.sql
└── 000001_initial.down.sql
```

```bash
# 本地安装 golang-migrate CLI 后:
migrate -path deploy/infra/migrations/gateway \
        -database "postgres://aiqa:aiqa_secure_pass_2026@localhost:5432/aiqa_gateway?sslmode=disable" \
        up
```

**Docker 部署:**
- `rag-migration` 容器使用自定义镜像运行 Alembic，依赖于 Python 运行时
- `gateway-migration` 容器使用官方 `migrate/migrate:v4.18.1` 镜像，无需任何语言运行时
- 两个容器均使用 `condition: service_completed_successfully` 确保迁移成功后再启动对应服务

**新增迁移:**
```bash
# RAG (Alembic)
alembic -c deploy/infra/migrations/rag/alembic.ini revision -m "add_column_x"

# 网关 (golang-migrate) — 手动创建 .up.sql / .down.sql 文件
# 命名格式: {版本号}_{描述}.up.sql / {版本号}_{描述}.down.sql
touch deploy/infra/migrations/gateway/000002_add_user_preferences.up.sql
touch deploy/infra/migrations/gateway/000002_add_user_preferences.down.sql
```


```
Knowledge Base (知识库)
├── Collections (集合/分类)
│   ├── Documents (文档) → 原始文件 → MinIO
│   │   └── Chunks (文本块) → 向量 → Milvus
│   ├── Web Pages (网页)
│   └── API Data Sources (API 数据源)
└── Access Control (权限)
    ├── KB-Level Permissions
    ├── Document-Level Permissions
    └── Query Permissions
```

### 知识源接入

| 知识源 | 接入方式 | 同步策略 |
|--------|---------|---------|
| PDF/Word 文档 | 上传 / 批量导入 | 全量重建 / 增量更新 |
| 网页/在线文档 | 爬虫 / API 拉取 | 定时同步 + 变更检测 |
| 数据库/API | 数据连接器 | 定时同步 / CDC |
| Git 仓库 | Webhook 触发 | PR/MR 触发增量索引 |

---

## 6. Prompt 模板设计与来源引用

代码位置: `backend/rag-service/app/llm/llm_service.py` → `SYSTEM_PROMPT_TEMPLATE`

### 强制引用规则

每个关键观点、数据、结论都必须在末尾用 `[Doc-N]` 格式标注来源文档编号：

```
系统的端口配置在 config.yaml 中 [Doc-1][Doc-2]
如果使用 HTTPS，还需要配置证书路径 [Doc-3]
```

### 上下文中的文档标记

Pipeline 在构建上下文时，为每个文档块生成唯一标记：

```
[Doc-1] 🔍 向量匹配 | 来源: 部署指南.pdf
  文档ID: abc-123 | 相关度: 0.8921
  内容: ...
---
[Doc-2] 🔑 关键词匹配 | 来源: config-说明.md
  文档ID: def-456 | 相关度: 0.7543
  内容: ...
---
```

### 模板结构

```
你是一个专业的企业知识库 AI 助手。你的职责是基于提供的知识库内容回答用户问题。

## 核心原则
1. 基于知识库回答，不要编造信息
2. 引用来源: 每个关键观点标注 [来源: 文档名称]
3. 不确定性处理:
   - 信息不足 → 告知并给出已有信息
   - 无相关信息 → 坦诚告知
4. 格式清晰: Markdown 组织、结构化呈现

## 输入结构
- {context} → 检索到的文档片段
- {history} → 最近对话历史
- {question} → 用户当前问题
```

---

## 7. 安全与审计

| 维度 | 措施 |
|------|------|
| **内容安全** | 回答前过滤 + 回答后审核，敏感词库 |
| **幻觉控制** | 强制引用来源，无法回答时明确告知 |
| **数据隐私** | 纯本地部署，数据零出网 |
| **访问控制** | JWT 认证 + RBAC 权限 (admin/editor/user/viewer) |
| **审计** | 完整审计日志 (谁/何时/做了什么/操作了什么资源) |
| **文档隔离** | 知识库级别隔离，文档级访问控制 |

---

## 8. 监控指标

```
┌──────────────────────────────────────────┐
│               Grafana 仪表盘               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ LLM 监控   │ │ 检索质量   │ │ 系统资源   │  │
│  │ - 延迟分布  │ │ - Top-K    │ │ - GPU 利用率│  │
│  │ - Token 量 │ │ 命中率     │ │ - 内存/显存 │  │
│  │ - QPS / TPS│ │ - Reranker │ │ - 磁盘 IO  │  │
│  │ - 错误率    │ │ 提升率     │ │ - 网络流量  │  │
│  └──────────┘ └──────────┘ └──────────┘  │
└──────────────────────────────────────────┘
```

**告警阈值**:
- P99 延迟 > 5s → 告警 (检查 LLM API 延迟和网络)
- 检索命中率 < 70% → 告警 (需补充知识库)
- GPU 显存 > 90% → 告警 (嵌入/重排 GPU)
- 答案空回复率 > 5% → 告警 (检查 LLM API 和 Pipeline)
- LLM API 错误率 > 1% → 告警 (检查 API Key 和网络)

---

## 9. 代码架构与扩展性设计

> 本文档是 Phase 2/3 扩展的架构基础。遵循"面向接口 + 依赖注入 + Pipeline 编排"模式。

### 9.1 核心抽象接口层 (Protocols)

**代码位置**: `app/core/protocols.py`

所有外部服务通过抽象接口定义，实现可替换、可测试：

```
VectorStore      ← MilvusStore、QdrantStore、PGVectorStore (纯向量)
KeywordStore     ← MilvusBM25Store、PGFTSStore、SimpleBM25Store (纯关键词)
EmbeddingModel   ← BGE-M3、OpenAIEmbedding、LocalEmbedding
Reranker         ← BGE-Reranker、CohereReranker
LLMProvider      ← OpenAICompatibleProvider (vLLM/DeepSeek/OpenAI/Ollama等)、AnthropicProvider
QueryPipeline    ← NaiveRAGPipeline、AgenticRAGPipeline (Phase 2)
```

**为什么不是 Singleton**:
```python
# ❌ 旧代码: 硬编码单例
from app.retrieval.milvus_client import milvus_client  # 无法替换

# ✅ 新代码: 面向接口
from app.core.protocols import VectorStore
from app.core.container import get_vector_store  // 可注入任何实现
```

添加新向量库只需实现 `VectorStore` 接口，无需修改现有代码。

### 9.2 依赖注入容器 (Container)

**代码位置**: `app/core/container.py`

统一管理所有服务实例的创建和生命周期：

```
Container
├── get_vector_store()    → MilvusClient (可换 Qdrant)
├── get_embedding_model() → EmbeddingManager (可换 API)
├── get_reranker()        → RerankerService
├── get_llm_router()      → LLMRouter (主+备模型)
├── get_pipeline()        → NaiveRAGPipeline (可换 AgenticRAG)
├── initialize_all()      → 启动时调用
└── close_all()           → 关闭时调用
```

**添加新实现只需三步**:
```
1. 实现抽象接口 (class MyStore(VectorStore))
2. 在 Container 中注册 (get_vector_store → MyStore)
3. 配置生效
```

### 9.3 LLM 双协议路由与降级

**代码位置**: `app/core/llm_router.py` + `app/llm/providers.py`

#### 双协议支持

系统支持 **两种 API 协议**，通过 `LLM_API_FORMAT` 配置选择。LLM 全部通过 API 接入，不部署本地推理模型：

| 协议 | 类 | 适用供应商 | API 端点 |
|------|----|-----------|---------|
| **OpenAI 兼容格式** | `OpenAICompatibleProvider` | vLLM(本地)、OpenAI、DeepSeek、Ollama、Groq 等 | `/v1/chat/completions` |
| **Anthropic Messages 格式** | `AnthropicProvider` | Claude 系列 (Sonnet/Haiku/Opus) | `/v1/messages` |

供应商通过 `LLM_PROVIDER` 配置,影响默认端点、API Key 策略和指标标签：

| 供应商 | 默认端点 | 需 Key | 适用场景 |
|--------|---------|--------|---------|
| `vllm` | `http://localhost:8000/v1` | ❌ | 内网 vLLM 服务器（可选） |
| `ollama` | `http://localhost:11434/v1` | ❌ | 本地 Ollama 部署 |
| `deepseek` | `https://api.deepseek.com` | ✅ | DeepSeek 官方 API |
| `openai` | `https://api.openai.com/v1` | ✅ | OpenAI GPT 系列 |
| `anthropic` | `https://api.anthropic.com/v1` | ✅ | Anthropic Claude 系列 |
| `groq` | `https://api.groq.com/openai/v1` | ✅ | Groq 快速推理 |

#### 自动降级流程

```
主模型调用
    │
    ├── 成功 → 正常返回
    │
    └── 失败 (超时/错误/熔断)
         │
         ├── 有备用模型? → 自动切换，标记 fallback 模式
         │                   回复附加 "(由备用模型回答)"
         │
         └── 无备用模型 → 返回 "AI 服务不可用"
```

#### 熔断器参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| failure_threshold | 3 | 连续失败 N 次开启熔断 |
| recovery_timeout | 30s | 熔断后等待恢复时间 |
| half_open_max | 1 | 半开状态允许的探测请求数 |

#### 超时与防无限循环

```python
# 单次调用超时
LLM_TIMEOUT = 60            # 秒

# 单次问答累计 Token 上限 (防 Agent Loop 无限循环)
LLM_MAX_TOTAL_TOKENS = 16384

# 重试
LLM_MAX_RETRIES = 2         # 失败重试次数
```

#### 配置示例

```bash
# 方案 A: DeepSeek API (主) + Anthropic Claude (备用)
LLM_API_FORMAT=openai
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-deepseek-key

LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_API_FORMAT=anthropic
LLM_FALLBACK_PROVIDER=anthropic
LLM_FALLBACK_MODEL=claude-sonnet-4-20250514
LLM_FALLBACK_API_KEY=sk-ant-key

# 方案 B: Anthropic Claude (带思考模式)
LLM_API_FORMAT=anthropic
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
LLM_API_KEY=sk-ant-xxxxx
LLM_THINKING_ENABLED=true
LLM_THINKING_BUDGET=4096

# 方案 C: 内网 vLLM 服务器 (有独立 GPU 机器时)
LLM_API_FORMAT=openai
LLM_PROVIDER=vllm
LLM_MODEL=deepseek-r1
LLM_BASE_URL=http://gpu-server:8000/v1
# 无需 API Key，也不配备用模型（内网可用时不需要）
```

### 9.4 Pipeline 编排器

**代码位置**: `app/core/pipeline.py`

Pipeline 是查询执行的抽象层，路由层只负责 HTTP 序列化：

```
Before:                          After:
┌─────────────────────┐         ┌─────────────────────┐
│ routes.py           │         │ routes.py (薄)       │
│  检索 → 重排 → 生成   │   →    │  仅解析请求/返回响应   │
│  (所有业务逻辑)      │         │  pipeline.execute()  │
└─────────────────────┘         └──────────┬──────────┘
                                           │
                                  ┌────────▼────────┐
                                  │ QueryPipeline    │
                                  │  (可替换实现)     │
                                  └─────────────────┘
```

**Phase 2 扩展方式**: 新增 `AgenticRAGPipeline`，仅需修改配置:

```python
# config/settings.py
PIPELINE_TYPE = "agentic-rag"  # 从 naive-rag 切换

# app/core/container.py
if pipeline_type == "agentic-rag":
    self._pipeline = AgenticRAGPipeline(...)  # 新增文件，不修改旧文件
```

### 9.5 熔断与重试

**代码位置**: `app/core/circuit_breaker.py`

```python
from app.core.circuit_breaker import with_retry, CircuitBreaker

# 一次调用: 带重试 + 熔断 + 超时
result = await with_retry(
    fn=my_async_function,
    max_retries=3,
    base_delay=1.0,       // 指数退避: 1s, 2s, 4s
    circuit_breaker=cb,    // 熔断器
    timeout=30.0,          // 超时
)
```

### 9.6 持久化缓存

**代码位置**: `app/core/cache.py`

| 层级 | 用途 | 失效策略 |
|------|------|---------|
| Redis (热) | 对话历史缓存 | TTL=7200s (2h) |
| PostgreSQL (冷) | 永久存储 | 无过期 |

```
对话消息 → ConversationCache.append_message()
               │
          Redis SETEX conv:{id}
               │
          消息写入 → 下次查询直接读取
```

### 9.7 配置中心

**代码位置**: `config/settings.py`

配置覆盖优先级: **环境变量 > .env 文件 > 默认值**

```bash
# 用环境变量覆盖任何配置
export LLM_API_FORMAT=openai
export LLM_PROVIDER=deepseek
export LLM_API_KEY=sk-xxxx
export LLM_FALLBACK_ENABLED=false
```

### 9.8 Phase 2/3 扩展路径

| 特性 | 具体操作 | 改动范围 |
|------|---------|---------|
| **Agent Loop** | 新增 `AgenticRAGPipeline` 实现 `QueryPipeline` | 新增 1 文件, 改 1 配置 |
| **工具调用** | 实现 `ToolRegistry`, LLM 自主选择工具 | 新增 1 模块 |
| **技能注册** | 实现 `SkillRegistry`, 与 ToolRegistry 联动 | 新增 1 模块 |
| **换向量库** | 实现 `QdrantStore(VectorStore)` | 新增 1 文件, 改 Container |
| **换嵌入** | 实现 `OpenAIEmbedding(EmbeddingModel)` | 新增 1 文件, 改 Container |
| **多模型负载均衡** | LLMRouter 支持多主模型轮询 | 改 LLMRouter |
| **单元测试** | Mock 各接口, 每个实现独立测试 | 新增 `tests/` 目录 |
