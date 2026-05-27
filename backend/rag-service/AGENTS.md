# AGENTS.md — Python RAG 服务

## 技术栈

Python 3.14.5 / FastAPI 0.109 / Milvus 2.5 / BGE-M3 / DeepSeek + vLLM

## 必须知道的命令

```bash
# 安装依赖 (从 rag-service/ 目录)
pip install -r requirements.txt

# 开发运行 (从 rag-service/ 目录，因为 python -m app.main 需要 app 包在 cwd)
python -m app.main                     # → localhost:8001

# Docker 构建 (context 必须是项目根目录)
docker build -f deploy/Dockerfile.rag -t ai-qa-rag .

# 无测试
# 无 linter/formatter 配置 (没有 black/ruff/pytest)
```

## 架构

面向接口 + 依赖注入 + Pipeline 编排。所有外部依赖通过抽象接口隔离。

```
app/core/protocols.py     — 抽象接口 (ABC): VectorStore, KeywordStore, LLMProvider 等
app/core/container.py     — 依赖注入容器 (单例模式, 懒加载)
app/core/pipeline.py      — NaiveRAGPipeline: 检索→重排→生成 编排
app/core/llm_router.py    — 主/备 LLM 自动降级
app/core/circuit_breaker.py — 熔断器 + 指数退避重试
```

### 扩展方式

- 新增 LLM 供应商: 在 `llm/providers.py` 继承 `OpenAICompatibleProvider`，在 `container.py` 的 `_create_provider` 注册
- 新增向量库: 实现 `VectorStore` 接口，在 `container.py` 注册
- Pipeline 升级: 实现 `QueryPipeline` 接口的新类，改 `PIPELINE_TYPE` 配置

## 重要约定

### 异步与同步混用

所有 HTTP/IO 操作用 `async def` + `httpx.AsyncClient`。但 `sentence-transformers` 和 `transformers` 的推理是**同步阻塞**的 — 在 `await` 上下文中直接调用可能阻塞事件循环。当前代码未对此做特殊处理。

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
日志器按 `__name__` 命名，主要使用 `info`/`warning` 级别。

## 测试

**无任何测试**。修改后需手动启动服务验证。
