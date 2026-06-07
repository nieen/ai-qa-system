# ROADMAP.md — 项目发展规划

> 企业 AI 智能问答系统的中长期发展规划，按阶段划分。Phase 1 为已交付内容，Phase 2~4 为后续路线图。

---

## 已完成 · Phase 1

> 截至 2026-06-07，以下核心功能已全部交付。项目已标记为 v1.0.0 版本。

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

> **备注**: Phase 1 交付时未配置 CI/CD 流水线（将在 Phase 2 补充）。性能基线数据（检索 P99 / 端到端延迟 / 吞吐量）将在 Phase 2 性能优化开始前统一采集，以便优化前后对比。

---

## 过渡 · Phase 1.5 — 基线采集与基础可观测

> Phase 2 启动前必须完成，为后续优化提供参照系。以下条目全部完成后才能进入 Phase 2。

- [ ] **检索 P99 延迟** — 记录当前混合检索的 P50 / P95 / P99 延迟基线
- [ ] **端到端问答延迟** — 记录从请求到完成响应的 P50 / P95 / P99
- [ ] **首 Token 时间（TTFT）** — 记录流式输出中首个 token 的到达时间
- [ ] **单节点吞吐量上限** — 加压测试确定单节点稳定 QPS 上限
- [ ] **LLM API 调用延迟分布** — 按供应商/模型分别记录延迟基线
- [ ] **基础 Grafana 仪表盘** — 至少覆盖检索延迟面板 + LLM 延迟面板（从 Phase 4 提前）

---

## 近期 · Phase 2

### Agentic RAG

- [ ] **Agent Loop 设计（ReAct 模式）** — 实现 Thought → Action → Observation → ... 循环：
  - 最大迭代轮数可配置（默认 8 轮），超限自动终止并返回已有结果
  - 每轮 Token 预算受 `LLM_MAX_TOTAL_TOKENS` 约束，防止无限消耗
  - Tool Call 结果注入下一轮 Prompt 的 System Message 层，保持上下文清晰
  - 循环终止条件：LLM 输出 Final Answer 或达到最大轮数
- [ ] **AgenticRAGPipeline** — 实现 `QueryPipeline` 接口的新编排器，支持查询改写、多轮推理、工具调用
- [ ] **ToolRegistry** — 内置工具清单：

  | 工具 | 优先级 | 说明 |
  |------|--------|------|
  | `retrieve_knowledge(query)` | **P0** | 检索知识库（包装现有混合检索流程） |
  | `web_search(query)` | P1 | 联网搜索（可选，需 API Key） |
  | `calculate(expression)` | P1 | 简单计算 / 单位转换 |
  | `get_current_time()` | P2 | 时间 / 日期查询 |
  | `summarize(text)` | P2 | 长文本摘要工具 |

- [ ] **SkillRegistry** — 技能注册系统，与 ToolRegistry 联动
- [ ] **Agent 流式输出** — Thought → Action → Observation 过程通过 SSE 逐步展示到前端，前端需对应改造
- [ ] **Tool Call 降级策略** — 工具执行失败不终止循环，Observation 返回失败信息，由 LLM 决定重试/换策略/降级回答
- [ ] **成本联动** — Agent 多轮调用会倍增 Token 消耗，需与 Phase 3 成本管理联动，Agent Loop 内部记录每轮 Token 消耗
- [ ] **多模型负载均衡** — LLMRouter 支持多主模型轮询，按权重分配请求

### 🚀 语义缓存（高优先级）

- [ ] **语义缓存** — 对语义相似查询直接返回缓存结果，减少重复检索：
  - 嵌入向量 + HNSW 近似匹配，判断查询语义相似度（阈值可配置，默认 0.92）
  - 缓存 TTL 配置化（默认 10 分钟）
  - 缓存命中率、存储量暴露为 Prometheus 指标
  - 与现有 `conversation_cache` 互补（一个缓存检索结果，一个缓存对话状态）
  - **预期收益**: 命中时检索延迟接近 0，整体命中率取决于查询重复模式；未命中时额外 embedding 开销应 < 50ms，需暴露"缓存开销/收益比"指标

### RAG 质量评估 MVP

- [ ] **LLM-as-Judge 评分** — 至少覆盖 Answer Relevance 一个指标，为 Agentic RAG 和语义缓存提供优化前后的对比参照
- [ ] **评估集构建** — 从 Phase 3 用户反馈 + 人工标注构建基础评估集，优先覆盖高频查询类型

### CI/CD 与工程基建

- [ ] **GitHub Actions CI 流水线** — `.github/workflows/ci.yml`，覆盖：
  - Go 网关: `go build` + `go test ./...`
  - Python RAG: `pytest` + 语法检查
  - 前端: `tsc --noEmit` + `vitest run` + `next build`
  - 分支保护：main 分支禁止直接推送，合入前 CI 必须通过
- [ ] **Docker 镜像构建流水线** — CI 通过后自动构建并推送 gateway / rag-service / frontend 镜像
- [ ] **数据库 Migration 校验** — 在 CI 中检查 migration 脚本一致性（工具待选：golang-migrate / Alembic）
- [ ] **CHANGELOG.md** — 按 Keep a Changelog 格式维护，自动或手动生成
- [ ] **CONTRIBUTING.md** — 贡献指南（如项目开放协作）

### 测试与质量

- [ ] **Go 网关测试覆盖** — handler 层和 middleware 层补充测试（当前 23 → 50+）
- [ ] **前端端到端测试** — 引入 Playwright，覆盖登录/问答/上传核心流程
- [ ] **RAG 集成测试** — 针对完整 Pipeline（检索→重排→生成）的集成测试
- [ ] **负载/压力测试** — 引入 locust/k6，目标：单节点 50 QPS 并发稳定
- [ ] **语义缓存集成测试** — 覆盖缓存命中/未命中/TTL 过期/向量相似度匹配
- [ ] **Agent Loop 边界测试** — 防御性测试：死循环保护、超限终止、空工具返回

### 性能优化

- [ ] **嵌入模型量化** — BGE-M3 INT8/FP16 量化，目标：显存占用从 ~4GB 降至 ~2GB
- [ ] **检索延迟优化** — Milvus 索引参数调优（nlist/nprobe）；目标：P99 < 500ms
- [ ] **前端构建优化** — 代码分割 / 图片优化 / 懒加载；目标：LCP < 2.5s, FID < 100ms, CLS < 0.1

---

## 中期 · Phase 3

### 生态扩展

- [ ] **向量库可替换** — 实现 `QdrantStore` / `PGVectorStore`（当前仅 Milvus）
- [ ] **嵌入模型可替换** — 实现 `OpenAIEmbedding` / 国产模型 API 接入
- [ ] **Git 仓库接入** — Webhook 触发增量索引，支持 PR/MR 自动同步
- [ ] **Bot 适配器框架（优先于具体平台对接）** — 先抽象接口再实现具体平台：
  - `BotAdapter` 接口：`send_message()` / `handle_event()`
  - 平台实现：企业微信 / 飞书 / 钉钉 / Slack
  - 与 AgenticRAGPipeline 联动

### 多租户

- [ ] **多租户支持** — 当前为单租户架构，企业级场景的必选项：
  - 知识库按租户隔离（Milvus Partition / Collection 级别）
  - 用户/角色/权限按租户独立
  - 租户级配额管理（文档数 / 存储 / API 调用量）
  - 租户级审计日志

### 用户反馈系统

- [ ] **用户反馈闭环** — 问答系统的持续改进离不开反馈数据：
  - 回答 thumbs up/down（前端已有元素，需补充后端持久化 + API）
  - 用户手动纠错（编辑回答、补充引用）
  - 反馈数据 → 评估集 → 触发 Pipeline 优化

### 体验升级

- [ ] **WebSocket 实时通知** — 文档索引完成、系统告警实时推送
- [ ] **多轮对话上下文压缩** — 长对话自动摘要、历史管理
- [ ] **知识库版本管理** — 文档级快照（MinIO 对象存储历史版本），回滚后自动重建向量索引
- [ ] **管理控制台** — 可视化知识库/用户/审计日志管理界面

### 可观测性增强

- [ ] **OpenTelemetry 采样率策略** — 全量采样在高 QPS 下成本高，支持概率采样（如 10%）

---

## 远期 · Phase 4

### RAG 质量评估

- [ ] **RAG 质量评估框架** — 量化优化效果的基础设施：
  - 自动评估 Pipeline：给定 (query, context, answer) 三元组
  - 评估指标：Answer Relevance / Context Precision / Faithfulness
  - RAGAS / TruLens 等开源框架集成
  - 回归测试集持续扩充（从用户反馈中采集）

### 成本管理

- [ ] **成本追踪与管理** — 企业落地时 CTO 最关心的问题：
  - 每次问答的 Token 消耗记录
  - 按用户 / 部门 / 知识库的成本聚合
  - 月度预算告警
  - 成本优化建议（哪些查询可以走缓存 / 小模型）

### 能力增强

- [ ] **多模态支持** — 图片 OCR、表格识别、图表理解
- [ ] **Reranker 升级** — 替换或叠加 cohere-rerank / 自训练重排模型
- [ ] **模型微调** — 基于知识库内容的 LoRA/QLoRA 微调

  > ⚠️ **风险提示**: LoRA 微调需要至少 500-1000 条高质量 Q&A 对；微调后需持续评估防止灾难性遗忘；建议先做 Prompt 工程优化和检索质量提升，微调作为最后手段。

### 安全与合规

- [ ] **文档级 ACL** — 细粒度权限控制，文档级访问策略
- [ ] **LDAP/OAuth2 集成** — 企业统一身份认证
- [ ] **数据加密** — 静态加密（PostgreSQL TDE / MinIO SSE）和传输加密（TLS）

### 运维与可观测

- [ ] **高级 Grafana 仪表盘** — 成本分析、用户行为、Agent 推理链路等面板（基础面板已提前至 Phase 1.5）
- [ ] **告警规则** — 基于 Prometheus 的自动告警（延迟/错误率/命中率）
- [ ] **自动扩缩容** — Worker 副本数根据队列深度自动调整

---

## 跨阶段关注项

以下问题不属于单一 Phase，贯穿项目生命周期：

| 问题 | 归属 | 说明 |
|------|------|------|
| **版本号策略** | ✅ 已定 | Phase 1 已完成，标记为 v1.0.0，后续按 SemVer 管理 |
| **LICENSE** | ✅ 已补 | MIT License（见根目录 LICENSE） |
| **postcss.config.mjs 位置** | ✅ 已确认 | 正确位于 `frontend/ai-qa-app/` 下，无路径问题 |
| **CI/CD 流水线** | Phase 2 | `.github/workflows/ci.yml`，跑 lint + test + build |
| **CHANGELOG.md** | Phase 2 | 按 Keep a Changelog 格式维护 |
| **CONTRIBUTING.md** | Phase 2 | 贡献指南 |
| **负载/压力测试** | Phase 2 | 引入 locust/k6，50 QPS 单节点目标 |
| **语义缓存** | Phase 2 | 高优先级，命中时检索延迟接近 0，实际命中率取决于查询模式 |
| **多租户** | Phase 3 | 企业级部署前提 |
| **用户反馈系统** | Phase 3 | 持续优化的数据来源 |
| **成本追踪** | Phase 4 → **提前至 Phase 3** | CTO 决策依据 |
| **RAG 质量评估** | Phase 4 → **提前至 Phase 3** | 量化优化效果的基础设施 |
| **Bot 适配器抽象** | Phase 3 | 避免重复对接劳动 |
| **数据库 Migration 策略** | Phase 2 | Schema 变更需版本化管理，Phase 2 CI/CD 中纳入 |
| **API 文档自动生成** | Phase 2 | API 契约变化时自动更新 Swagger |
| **日志结构化（JSON）** | Phase 2 | Grafana / 日志平台检索前提 |
| **LLM 评估集构建策略** | Phase 2 后期 | 从用户反馈 + 人工标注构建评估集 |
| **OpenTelemetry 采样率** | Phase 3 | 高 QPS 下降低成本 |
