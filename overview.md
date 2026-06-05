# 企业 AI 智能问答系统 - 项目全景

## 已完成内容

### 架构设计与技术选型
- 完整的 5 层架构: 前端层 → API 网关层 → RAG 服务层 → AI 引擎层 → 数据存储层
- 技术栈: Next.js + Go(Gin) + Python(FastAPI/LlamaIndex) + Milvus + PostgreSQL + Redis + MinIO
- LLM: DeepSeek + vLLM (本地推理)
- 嵌入: BGE-M3 (稠密+稀疏双通道)
- 重排序: BGE-Reranker (精排提升 15-25%)

### 已交付模块

| 模块 | 文件数 | 核心能力 |
|------|--------|---------|
| **基础设施** | 3 | Docker Compose (Milvus/PostgreSQL/Redis/MinIO), 数据库 Schema, 配置 |
| **Go API 网关** | 8 | 路由注册, JWT 认证, 限流熔断, 请求重试, Prometheus 指标, SSE 流式转发, 下游健康检查 |
| **Python RAG 服务** | 23 | 文档解析(5种格式), 向量化(BGE-M3), 混合检索(稠密+BM25), RRF 融合, 重排序, LLM 流式问答, Redis Streams 任务队列, OpenTelemetry 追踪, Prometheus 指标, JSON 结构化日志 |
| **文档索引 Worker** | 2 | 独立进程消费 Redis Streams, 支持多副本负载均衡, XCLAIM 死信重试 |
| **Next.js 前端** | 6 | 聊天界面(流式输出), 文档上传, 来源展示, Markdown 渲染 |
| **测试套件** | 8 | Python 75 测试 (pytest + fakeredis + httpx), Go 23 测试, 覆盖率 ~45% |
| **部署与文档** | 6 | README, Dockerfile×2, 启动脚本×2, 环境配置 |

### 项目路径
`F:\Coding\ai-qa-system\`

### 启动方式
```powershell
# Windows
.\deploy\startup.ps1

# Linux/Mac
chmod +x deploy/startup.sh && ./deploy/startup.sh

# 或手动分步启动 (推荐开发用)
deploy/infra/docker-compose up -d          # 基础设施
python -m app.main                          # RAG 服务 (端口 8001)
go run cmd/main.go                          # API 网关 (端口 8080)
npm run dev                                 # 前端 (端口 3000)
```

### 默认访问
- 前端: http://localhost:3000
- API: http://localhost:8080
- RAG 服务: http://localhost:8001
- Milvus 控制台: http://localhost:9091
- MinIO 控制台: http://localhost:9001
- 管理员: admin / admin123

---

> 详细架构设计（分块策略、向量数据库选型、两路并行检索流程）请查阅 **[ARCHITECTURE.md](./ARCHITECTURE.md)**。
> 部署指南和用户手册请查阅 **[docs/](./docs/)** 目录。
