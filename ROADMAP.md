# ROADMAP.md — 项目发展规划

> 企业 AI 智能问答系统的中长期发展规划，按阶段划分。

---

## 已完成 · Phase 1

> 截至 2026-06-07，以下核心功能已全部交付。

### RAG 核心流程

- [x] **混合检索** — 稠密向量（BGE-M3）+ BM25 关键词 + RRF 融合 + BGE-Reranker 精排
- [x] **文档索引** — 支持 PDF / Word / Markdown / HTML / 纯文本 5 种格式自动解析分块
- [x] **分块策略** — 三层混合（Markdown 标题分割 / 固定窗口 / 小段落合并），512 tokens
- [x] **查询改写** — 历史上下文补全，多轮对话支持
- [x] **上下文管理** — 分层压缩策略（> 6 轮自动摘要），防止 Token 溢出
- [x] **Prompt 模板** — 强制来源引用 `[Doc-N]`，无法回答时明确告知

### LLM 接入

- [x] **双协议支持** — OpenAI 兼容格式 + Anthropic Messages 格式
- [x] **多供应商** — DeepSeek（推荐）/ Claude / OpenAI
- [x] **自动降级** — 主模型失败自动切换备用模型，支持不同供应商交叉备用
- [x] **自动恢复** — 备用模式连续成功 3 次后自动切回主模型
- [x] **思考模式** — 支持 Anthropic 思考模式 + OpenAI reasoning_effort
- [x] **熔断器** — 本地 + 分布式双重实现，Redis Lua 脚本保证原子性
- [x] **重试 + 指数退避** — 带随机 jitter，避免惊群效应

### API 网关

- [x] **JWT 认证** — HS256 签发 + Redis 黑名单，登出即时失效
- [x] **RBAC 权限** — admin / editor / user / viewer 四级角色
- [x] **限流** — 令牌桶 100 req/s + Redis 分布式滑动窗口
- [x] **审计日志** — 所有 POST/PUT/DELETE 记录（含 IP / User-Agent），180 天自动清理
- [x] **PIPL 合规** — 数据导出（§45）、账号删除（§47，7 天冷静期）、隐私政策同意
- [x] **SSE 流式代理** — 逐行转发，支持长连接
- [x] **优雅关闭** — signal.Notify + http.Server.Shutdown
- [x] **Swagger 文档** — `/swagger/*any` 在线 API 文档

### 前端界面

- [x] **SSE 流式输出** — 打字机效果，逐 token 实时显示
- [x] **Markdown 渲染** — react-markdown + remark-gfm，代码块/表格/列表
- [x] **来源引用** — 回答底部展示引用文档片段 + 相关度评分
- [x] **认证 UI** — 登录/注册模态框 + 隐私政策勾选
- [x] **暗色模式** — light / dark / system 三模式
- [x] **文档上传 + 轮询** — 上传后每 2s 轮询索引状态，60s 超时
- [x] **数据合规 UI** — 导出数据、注销账号
- [x] **CSP 安全头** — Content-Security-Policy / X-Frame-Options
- [x] **ARIA 可访问性** — aria-live / role="dialog" / autoFocus

### 事件驱动架构

- [x] **Redis Streams** — 文档索引任务通过消费者组分发
- [x] **独立 Worker 进程** — 与 API 服务解耦，支持多副本负载均衡
- [x] **死信重试** — Pending Entries + XCLAIM，最多重试 3 次
- [x] **多副本安全** — Container 实例模式 + GPU run_in_executor

### 基础设施

- [x] **Docker Compose** — Milvus + PostgreSQL + Redis + MinIO 一键启动
- [x] **数据库 Schema** — users / knowledge_bases / documents / conversations / audit_logs 等完整结构
- [x] **PostgreSQL 双服务共用** — 网关管理用户/审计，RAG 管理对话/文档/知识库
- [x] **Redis 双服务共用** — 网关用于限流/黑名单/熔断器，RAG 用于 Streams/缓存
- [x] **OpenTelemetry 追踪** — 全链路 span 埋点
- [x] **Prometheus 指标** — http_requests / llm_latency / retrieval_hits 等

### 测试覆盖

- [x] **Go 网关** — Go test 23 个（config / JWT / 熔断器）
- [x] **Python RAG** — pytest 75 个（API / Document / RRF / Pipeline / EventBus / Providers）
- [x] **前端** — Vitest 24 个（auth / api / utils）
- [x] **Mock 策略** — fakeredis / unittest.mock 模拟外部依赖

---

## 近期 · Phase 2

### Agentic RAG

- [ ] **AgenticRAGPipeline** — 实现 `QueryPipeline` 接口的新编排器，支持查询改写、多轮推理、工具调用
- [ ] **ToolRegistry** — LLM 可自主选择检索/计算/查询工具
- [ ] **SkillRegistry** — 技能注册系统，与 ToolRegistry 联动
- [ ] **多模型负载均衡** — LLMRouter 支持多主模型轮询，按权重分配请求

### 测试与质量

- [ ] **Go 网关测试覆盖** — handler 层和 middleware 层补充测试（当前 23 → 50+）
- [ ] **前端端到端测试** — 引入 Playwright，覆盖登录/问答/上传核心流程
- [ ] **RAG 集成测试** — 针对完整 Pipeline（检索→重排→生成）的集成测试

### 性能优化

- [ ] **嵌入模型量化** — BGE-M3 INT8/FP16 量化，降低显存占用
- [ ] **检索延迟优化** — Milvus 索引参数调优（nlist/nprobe），目标 P99 < 500ms
- [ ] **前端构建优化** — 代码分割、图片优化、Core Web Vitals 达标

---

## 中期 · Phase 3

### 生态扩展

- [ ] **向量库可替换** — 实现 `QdrantStore` / `PGVectorStore`（当前仅 Milvus）
- [ ] **嵌入模型可替换** — 实现 `OpenAIEmbedding` / 国产模型 API 接入
- [ ] **Git 仓库接入** — Webhook 触发增量索引，支持 PR/MR 自动同步
- [ ] **Bot 集成** — 企业微信 / 飞书 Bot 消息入口

### 体验升级

- [ ] **WebSocket 实时通知** — 文档索引完成、系统告警实时推送
- [ ] **多轮对话上下文压缩** — 长对话自动摘要、历史管理
- [ ] **知识库版本管理** — 文档版本对比、回滚
- [ ] **管理控制台** — 可视化知识库/用户/审计日志管理界面

---

## 远期 · Phase 4

### 能力增强

- [ ] **多模态支持** — 图片 OCR、表格识别、图表理解
- [ ] **Reranker 升级** — 替换或叠加 cohere-rerank / 自训练重排模型
- [ ] **模型微调** — 基于知识库内容的 LoRA/QLoRA 微调

### 安全与合规

- [ ] **文档级 ACL** — 细粒度权限控制，文档级访问策略
- [ ] **LDAP/OAuth2 集成** — 企业统一身份认证
- [ ] **数据加密** — 静态加密（PostgreSQL TDE / MinIO SSE）和传输加密（TLS）

### 运维与可观测

- [ ] **Grafana 仪表盘** — 预置 LLM 监控、检索质量、系统资源面板
- [ ] **告警规则** — 基于 Prometheus 的自动告警（延迟/错误率/命中率）
- [ ] **自动扩缩容** — Worker 副本数根据队列深度自动调整