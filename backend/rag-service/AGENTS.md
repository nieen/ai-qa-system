# AGENTS.md — Python RAG 服务

## 技术栈

Python 3.13+ / FastAPI 0.136.3 / Milvus 2.5 / BGE-M3 / LLM API (DeepSeek/Claude/OpenAI)

## 必须知道的命令

```bash
# 安装依赖 (从 rag-service/ 目录)
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 测试依赖 (pytest, fakeredis, httpx)

# 开发运行 (从 rag-service/ 目录，因为 python -m app.main 需要 app 包在 cwd)
python -m app.main                     # → localhost:8001

# Docker 构建 (context 必须是项目根目录)
docker build -f deploy/Dockerfile.rag -t ai-qa-rag .

# 运行测试
pytest tests/ -v                       # 75 个测试

# 指定测试文件
pytest tests/test_pipeline.py -v
```

## 架构

面向接口 + 依赖注入 + Pipeline 编排。所有外部依赖通过抽象接口隔离。

```
app/core/protocols.py     — 抽象接口 (ABC): VectorStore, KeywordStore, LLMProvider 等
app/core/container.py     — 依赖注入容器 (实例模式, 懒加载, 多副本安全)
app/core/pipeline.py      — NaiveRAGPipeline: 检索→重排→生成 编排
app/core/llm_router.py    — 主/备 LLM 自动降级
app/core/circuit_breaker.py — 熔断器 + 指数退避重试
app/core/event_bus.py     — 应用内事件总线 (文档索引事件)
app/core/cache.py         — 对话缓存 (Redis + PostgreSQL 双层级)
app/core/embeddings.py    — BGE-M3 嵌入管理 (稠密+稀疏)
app/core/database.py      — 数据库会话管理
app/core/metrics.py       — Prometheus 指标收集
app/core/tracing.py       — OpenTelemetry 链路追踪
```

### 事件驱动架构

文档索引从 `BackgroundTasks` 迁移到 **Redis Streams**：

- 上传文档 → 写入 Redis Stream `doc:index`
- Worker (`workers/document_worker.py`) 通过消费者组消费
- 支持多副本负载均衡（同 group name 自动分配）
- 死信重试: Pending Entries + XCLAIM，最多重试 3 次
- 零新增基础设施: Redis 已在运行，直接复用

### 扩展方式

- 新增 LLM 供应商: 在 `llm/providers.py` 继承 `OpenAICompatibleProvider` 或 `AnthropicProvider`，在 `container.py` 的 `_create_provider` 注册
- 新增向量库: 实现 `VectorStore` 接口，在 `container.py` 注册
- 新增关键词检索: 实现 `KeywordStore` 接口，在 `container.py` 注册
- Pipeline 升级: 实现 `QueryPipeline` 接口的新类，改 `PIPELINE_TYPE` 配置

## 重要约定

### 异步与同步混用

所有 HTTP/IO 操作用 `async def` + `httpx.AsyncClient`。但 `sentence-transformers` 和 `transformers` 的推理是**同步阻塞**的 — 通过 `run_in_executor` 移出事件循环，避免阻塞 GPU 推理。

### 静默降级 (关键!)

所有外部服务失败都**静默降级**，不抛致命异常，不阻止应用启动：
- Redis 不可用 → 内存模式
- Milvus 不可用 → 返回空结果
- LLM 主模型失败 → 自动切备模型
- 嵌入模型加载失败 → 随机向量兜底
- 重排序模型不可用 → 保持原始顺序

修改降级逻辑时**不要改成抛异常**，这会破坏整个系统的自愈能力。

### 类型注解

必须使用 `typing` / `typing_extensions` 进行类型声明，所有函数签名和公共方法必须有类型注解。

### 配置优先级

环境变量 > `.env` 文件 > 默认值（在 `config/settings.py` 定义）

### SSE 流式协议

问答接口 `POST /api/v1/knowledge-bases/{kb_id}/chat` 返回 SSE：
```
data: {"type": "token", "content": "文本片段"}
data: {"type": "metadata", "status": "retrieved", ...}
data: {"type": "done", "conversation_id": "...", "sources": [...]}
data: {"type": "error", "content": "错误信息"}
```

### 日志

标准库 `logging`，格式: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
日志器按 `__name__` 命名，主要使用 `info`/`warning` 级别。支持 JSON 结构化日志输出。

### LLM 全部 API 接入

**系统不部署本地 LLM 推理模型**。所有 LLM 调用通过 HTTP API 完成，支持 OpenAI 兼容格式和 Anthropic Messages 格式：

| 协议 | Provider 类 | 适用供应商 |
|------|------------|-----------|
| **OpenAI 兼容格式** | `OpenAICompatibleProvider` | DeepSeek、OpenAI、vLLM(内网服务器)、Ollama、Groq |
| **Anthropic Messages 格式** | `AnthropicProvider` | Claude 系列 (Sonnet/Haiku/Opus) |

> 嵌入模型 (BGE-M3) 和重排序模型 (BGE-Reranker) 仍在本地运行。它们负责文档向量化和检索精排，不涉及 LLM 推理。

### 多副本部署注意事项

- Container 不再用单例模式，每个进程创建独立实例
- 所有服务类 (`EmbeddingManager`, `RerankerService`, `MilvusClient`, `ConversationCache`) 使用实例变量替代类变量
- 线程安全: GPU 推理 (PyTorch/HuggingFace) 通过 `run_in_executor` 移出事件循环

## 测试

```bash
pytest tests/ -v              # 75 个测试，覆盖:
tests/
├── test_api.py               # API 路由 (httpx + TestClient)
├── test_document_processor.py # 文档解析与分块
├── test_event_bus.py         # 应用内事件
├── test_pipeline.py          # RAG Pipeline 编排
├── test_providers.py         # LLM Provider 工厂
├── test_rrf_merge.py         # RRF 融合算法
├── test_conftest.py          # fixtures (fakeredis mock)
```

Mock 策略：所有外部依赖（Milvus/Redis/PostgreSQL/LLM API）通过 fakeredis / unittest.mock 模拟。
