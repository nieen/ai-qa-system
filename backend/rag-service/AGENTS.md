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

```
上传 API → Redis Stream → (独立 Worker 进程) → 解析 → 向量化 → 写入 Milvus
```

- **Worker 是独立进程**: `workers/document_worker.py` 有自己的 `if __name__ == "__main__": main()` 入口，通过 `python -m workers.document_worker` 启动，与 RAG API 服务 (`python -m app.main`) 是两个独立的进程
- 上传文档 → 写入 Redis Stream `doc:index`
- Worker 通过消费者组消费，支持多副本负载均衡（同 group name 自动分配）
- 死信重试: Pending Entries + XCLAIM，最多重试 3 次
- 零新增基础设施: Redis 已在运行，直接复用

### 扩展方式

- 新增 LLM 供应商: 在 `llm/providers.py` 继承 `OpenAICompatibleProvider` 或 `AnthropicProvider`，在 `container.py` 的 `_create_provider` 注册
- 新增向量库: 实现 `VectorStore` 接口，在 `container.py` 注册
- 新增关键词检索: 实现 `KeywordStore` 接口，在 `container.py` 注册
- Pipeline 升级: 实现 `QueryPipeline` 接口的新类，改 `PIPELINE_TYPE` 配置

## 重要约定

### 职责分层

HTTP 层（`api/routes.py`）只做请求解析和响应返回，不包含业务逻辑。所有业务逻辑在 Pipeline 层（`core/pipeline.py`）编排。

### 异步与同步混用

所有 HTTP/IO 操作用 `async def` + `httpx.AsyncClient`。但 `sentence-transformers` 和 `transformers` 的推理是**同步阻塞**的 — 通过 `run_in_executor` 移出事件循环，避免阻塞 GPU 推理。

### 外部 API 保护

所有外部 API 调用（LLM / 嵌入远程降级 / 等）都必须设置 `timeout` 和重试策略，避免单个调用阻塞整个 pipeline。

### 静默降级 (关键!)

所有外部服务失败都**静默降级**，不抛致命异常，不阻止应用启动：
- Redis 不可用 → 内存模式
- Milvus 不可用 → 返回空结果
- LLM 主模型失败 → 自动切备模型
- 嵌入模型加载失败 → 随机向量兜底
- 重排序模型不可用 → 保持原始顺序

修改降级逻辑时**不要改成抛异常**，这会破坏整个系统的自愈能力。

### 类型注解

必须使用 `typing` / `typing_extensions` 进行类型声明，所有函数签名和公共方法必须有类型注解（`def func(arg: str) -> List[int]:` 风格）。

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
日志器按 `__name__` 命名，支持 JSON 结构化日志输出。

**日志级别规范**：
- `WARNING` — 可恢复问题（降级、重试、超时），不影响用户体验
- `ERROR` — 不可恢复问题（配置错误、数据库离线），可能阻塞功能
- 两者不可混用：可恢复的场景不要用 ERROR，不可恢复的不要用 WARNING

### LLM 全部 API 接入

LLM 全部通过 HTTP API 接入，RAG 服务不部署本地推理模型。嵌入模型和重排模型仍在本地运行。

### 多副本部署注意事项

- Container 不再用单例模式，每个进程创建独立实例
- 所有服务类 (`EmbeddingManager`, `RerankerService`, `MilvusClient`, `ConversationCache`) 使用实例变量替代类变量
- 线程安全: GPU 推理 (PyTorch/HuggingFace) 通过 `run_in_executor` 移出事件循环

### 外部依赖健壮性

- Milvus 操作有重试机制（`_retry_milvus()` 指数退避 1s/2s/4s，最大 3 次），不允许裸调用 pymilvus API

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
