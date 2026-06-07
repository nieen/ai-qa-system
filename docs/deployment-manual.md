# 部署手册

> 企业 AI 智能问答系统部署指南。适用于生产环境搭建和开发环境快速启动。

---

## 目录

- [1. 环境要求](#1-环境要求)
- [2. 部署架构](#2-部署架构)
- [3. 基础设施部署（Docker Compose）](#3-基础设施部署docker-compose)
- [4. 应用服务部署](#4-应用服务部署)
- [5. Docker 全容器化部署](#5-docker-全容器化部署)
- [6. 多副本部署（生产环境）](#6-多副本部署生产环境)
- [7. 配置指南](#7-配置指南)
- [8. LLM 模型部署](#8-llm-模型部署)
- [9. 健康检查与监控](#9-健康检查与监控)
- [10. 运维检查清单](#10-运维检查清单)
- [11. 常见问题](#11-常见问题)

---

## 1. 环境要求

### 1.1 硬件最低配置

| 组件 | 配置 | 说明 |
|------|------|------|
| **CPU** | 16 核 32 线程 | Milvus + PostgreSQL + 应用服务 |
| **内存** | 64 GB | 16GB (Milvus) + 16GB (应用) + 32GB (OS/缓存) |
| **GPU** | 可选 1× RTX 4090 24GB | 仅用于嵌入/重排序模型加速（可回退 CPU）|
| **硬盘** | 500GB+ NVMe SSD | 向量数据 + 文档存储 |
| **网络** | 1GbE 内网 + LLM API 出网 | 内网通信 + API 调用 |

### 1.2 软件依赖

| 软件 | 版本要求 | 说明 |
|------|---------|------|
| **Docker** | 24.0+ | 基础设施容器化 |
| **Docker Compose** | v2.20+ | 多容器编排 |
| **Go** | 1.26.3+ | API 网关（可选手动启动） |
| **Python** | 3.13+ | RAG 服务（可选手动启动） |
| **Node.js** | 22+ | 前端（可选手动启动） |
| **NVIDIA 驱动** | 550+ | GPU 加速嵌入/重排（可选） |
| **CUDA** | 12.4+ | GPU 加速嵌入/重排（可选） |

### 1.3 端口占用

| 端口 | 服务 | 说明 |
|------|------|------|
| 3000 | Next.js 前端 | Web 界面 |
| 8080 | Go API 网关 | 对外 API |
| 8001 | Python RAG 服务 | 内部 API |
| 5432 | PostgreSQL | 元数据存储 |
| 6379 | Redis | 缓存/任务队列 |
| 19530 | Milvus gRPC | 向量检索 |
| 9091 | Milvus HTTP | 管理控制台 |
| 9000 | MinIO API | 对象存储 |
| 9001 | MinIO Console | 管理控制台 |

---

## 2. 部署架构

```
                        ┌─────────────┐
                        │  外部用户    │
                        │  HTTPS:443  │
                        └──────┬──────┘
                               │
                    ┌──────────▼──────────┐
                    │   Nginx / LB         │  ← 反向代理、SSL 终结
                    │   (可选)             │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Go API 网关         │  ← 认证/限流/路由
                    │  :8080              │      用户/审计/PIPL
                    └──────┬──────┬───────┘
                           │      │
              ┌────────────▼┐  ┌─▼──────────────┐     ┌─────────────┐
              │ RAG 服务     │  │ RAG Worker      │     │ PostgreSQL   │
              │ FastAPI:8001 │  │ (文档索引消费者)  │ ◀───│ 用户/审计     │
              └──────┬───────┘  └─────┬──────────┘  │  │ 对话/文档/KB  │
                     │                │             │  │ (同一实例)    │
        ┌────────────┼───────────┬────┴──────────┐  │  └─────────────┘
        │            │           │                │  │
   ┌────▼───┐  ┌────▼───┐  ┌───▼────┐  ┌───────▼──┐ │
   │ Milvus │  │ Redis  │  │ MinIO  │  │ PgSQL    │ │
   │ :19530 │  │ :6379  │  │ :9000  │  │ :5432    │ │
   └────────┘  │ 限流/  │  └────────┘  └──────────┘ │
               │ 黑名单/  │                          │
               │ 熔断器/  │  ◀─── 网关 + RAG 共用     │
               │ Streams │                          │
               └─────────┘                          │
              PostgreSQL ◀─── 网关（用户/审计/PIPL）+ RAG（对话/文档/KB）共用
```

---

## 3. 基础设施部署（Docker Compose）

### 3.1 部署步骤

```bash
# 1. 进入部署目录
cd deploy/infra

# 2. 启动基础服务 (Milvus + PostgreSQL + Redis + MinIO)
docker compose up -d

# 3. 查看启动状态
docker compose ps

# 4. 查看实时日志
docker compose logs -f
```

### 3.2 启动的服务

| 服务名 | 容器名 | 说明 |
|--------|--------|------|
| `milvus-etcd` | `aiqa-etcd` | Milvus 元数据存储（分布式协调） |
| `milvus-minio` | `aiqa-milvus-minio` | Milvus 内置对象存储 |
| `milvus` | `aiqa-milvus` | 向量数据库主服务 |
| `postgres` | `aiqa-postgres` | 业务元数据、用户、对话 |
| `redis` | `aiqa-redis` | 会话缓存、限流、任务队列 |
| `minio` | `aiqa-minio` | 原始文档存储（非 Milvus 内置） |

### 3.3 验证基础设施就绪

```bash
# 健康检查端点
curl http://localhost:9091/health          # Milvus
curl http://localhost:5432                 # PostgreSQL
curl http://localhost:9001/minio/health/live  # MinIO
redis-cli -a aiqa_redis_pass_2026 ping     # Redis
```

---

## 4. 应用服务部署

### 4.1 一键启动（开发环境）

```powershell
# Windows (PowerShell)
.\deploy\startup.ps1
```

```bash
# Linux/Mac
chmod +x deploy/startup.sh && ./deploy/startup.sh
```

### 4.2 手动分步启动

#### 步骤 1: 配置环境变量

```bash
# 从模板创建 .env 文件
cp .env.example .env
# 编辑 .env，修改必要配置（API Key 等）
```

#### 步骤 2: 启动 RAG 服务

```bash
cd backend/rag-service

# 创建虚拟环境（首次）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 安装测试依赖（可选）
pip install -r requirements-dev.txt

# 启动服务
python -m app.main

# → 监听 http://localhost:8001
```

#### 步骤 3: 启动文档索引 Worker

```bash
# 新终端窗口
cd backend/rag-service
source venv/bin/activate  # Windows: venv\Scripts\activate

# 启动 Worker（可同时启动多个实现负载均衡）
python -m workers.document_worker worker-1
# 新窗口:
python -m workers.document_worker worker-2

# → 通过 Redis Streams 消费者组消费文档索引任务
```

#### 步骤 4: 启动 API 网关

```bash
cd backend/gateway
go mod tidy
go run cmd/main.go

# → 监听 http://localhost:8080
```

#### 步骤 5: 启动前端

```bash
cd frontend/ai-qa-app

# 创建环境变量（首次）
echo "NEXT_PUBLIC_API_BASE=http://localhost:8080/api/v1" > .env.local

# 安装依赖
npm install --silent

# 启动
npm run dev

# → 监听 http://localhost:3000
```

---

## 5. Docker 全容器化部署

### 5.1 构建 Docker 镜像

```bash
# 构建 RAG 服务镜像
docker build -t aiqa-rag-service:latest -f deploy/Dockerfile.rag .

# 构建 Gateway 镜像
docker build -t aiqa-gateway:latest -f deploy/Dockerfile.gateway .
```

### 5.2 启动全部服务

```bash
cd deploy/infra
docker compose --profile app up -d
```

这会启动以下服务：
- `rag-service` — RAG 服务 (port 8001)
- `rag-worker` — 文档索引 Worker (2 副本)
- `gateway` — API 网关 (port 8080, 单副本)

> **注意：** 前端未包含在 Docker Compose 中，需要单独启动。LLM API 配置详见第 8 节。

---

## 6. 多副本部署（生产环境）

### 6.1 扩缩容

```bash
# 启动 2 个 RAG 服务副本
docker compose up -d --scale rag-service=2

# 启动 3 个 Worker 副本
docker compose up -d --scale rag-worker=3

# 启动 2 个网关副本
docker compose up -d --scale gateway=2
```

### 6.2 多副本架构说明

```
用户请求
   │
   ▼
┌──────────────┐  ┌──────────────┐
│  Gateway #1   │  │  Gateway #2   │  ← 无状态，可水平扩展
│  :8080       │  │  :8081       │
└──────┬───────┘  └──────┬───────┘
       │                  │
       └────────┬─────────┘
                │ (Nginx 负载均衡)
       ┌────────▼─────────┐
       │  RAG Service #1   │  RAG Service #2
       │  :8001            │  :8002
       └────────┬─────────┘
                │
       ┌────────▼─────────┐
       │  RAG Worker 池     │  ← Redis Streams 消费者组负载均衡
       │  worker-1 ~ 3     │     崩溃 Worker 的任务被自动认领 (XCLAIM)
       └──────────────────┘
```

### 6.3 关键设计

| 机制 | 说明 |
|------|------|
| **容器无单例** | 所有服务类使用实例变量而非类变量，每个进程独立 |
| **GPU 线程安全** | PyTorch/HuggingFace 推理通过 `run_in_executor` 移出事件循环 |
| **Redis Streams 消费者组** | 多 Worker 竞争消费，崩溃后由其他 Worker 认领 |
| **Gateway 无状态** | JWT 认证、限流 state 存储于 Redis |
| **环境变量隔离** | 每个副本独立配置 |

---

## 7. 配置指南

### 7.1 配置优先级

```
环境变量 > .env 文件 > Settings.py 默认值
```

### 7.2 核心配置项

#### LLM 配置

```bash
# API 协议格式
LLM_API_FORMAT=openai              # openai | anthropic

# 供应商（影响默认端点）
LLM_PROVIDER=vllm                  # vllm | deepseek | openai | anthropic
LLM_MODEL=deepseek-r1              # 模型名（根据实际部署设置）
LLM_BASE_URL=                      # 留空则自动推导
LLM_API_KEY=                       # 远程 API 时需要

# 多模态
LLM_SUPPORTS_MULTIMODAL=false

# 思考模式（推理模型相关）
LLM_THINKING_ENABLED=false
LLM_THINKING_BUDGET=2048

# 备用模型
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_API_FORMAT=openai
LLM_FALLBACK_PROVIDER=deepseek
LLM_FALLBACK_MODEL=deepseek-chat
```

#### 检索配置

```bash
RETRIEVAL_TOP_K_VECTOR=30     # 向量检索召回数
RETRIEVAL_TOP_K_BM25=30       # BM25 检索召回数
RETRIEVAL_FINAL_TOP_K=5       # 最终送 LLM 的文档数
RETRIEVAL_SCORE_THRESHOLD=0.3 # 最低分数阈值
```

#### 文档分块

```bash
CHUNK_SIZE=512                # 每块 token 数
CHUNK_OVERLAP=64              # 相邻块重叠 token 数
```

### 7.3 安全配置

> ⚠️ **生产环境必须修改以下配置！**

```bash
# JWT 密钥（必须改为随机字符串）
JWT_SECRET=your-strong-random-secret-key-here

# CORS 限制（改为实际域名）
CORS_ALLOWED_ORIGINS=https://your-domain.com

# 数据库密码（必须修改）
POSTGRES_PASSWORD=your-strong-password
REDIS_PASSWORD=your-strong-password
```

---

## 8. LLM 配置

系统通过 API 接入 LLM，**不部署本地推理模型**。所有 LLM 调用通过 HTTP API 完成。

### 8.1 配置 API 供应商（推荐）

在 `.env` 中配置供应商和 Key：

```bash
# DeepSeek API（默认推荐 — 性价比高）
LLM_API_FORMAT=openai
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-deepseek-api-key
LLM_MODEL=deepseek-chat

# Anthropic Claude
LLM_API_FORMAT=anthropic
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-your-anthropic-api-key
LLM_MODEL=claude-sonnet-4-20250514

# OpenAI
LLM_API_FORMAT=openai
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-openai-api-key
LLM_MODEL=gpt-4o
```

### 8.2 备用模型配置

主模型不可用时自动降级，支持不同供应商交叉备用：

```bash
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_API_FORMAT=openai
LLM_FALLBACK_PROVIDER=deepseek
LLM_FALLBACK_MODEL=deepseek-chat
LLM_FALLBACK_API_KEY=sk-your-backup-key
```

### 8.3 内网 vLLM 服务器（有独立 GPU 机器时）

如果网络内有独立的 GPU 服务器运行 vLLM，可通过 `LLM_BASE_URL` 指向：

```bash
LLM_API_FORMAT=openai
LLM_PROVIDER=vllm
LLM_MODEL=deepseek-r1
LLM_BASE_URL=http://gpu-server:8000/v1
# 内网场景无需 API Key
```

---

## 9. 健康检查与监控

### 9.1 健康检查端点

| 端点 | 说明 | 预期响应 |
|------|------|---------|
| `GET /health` | 服务存活检查 | `{"status": "ok"}` |
| `GET /health/llm` | LLM 连接检查 | `{"status": "ok", "primary": true, ...}` |
| `GET /health/downstream` | 下游服务检查 | `{"status": "ok", "services": {...}}` |
| `GET /metrics` | Prometheus 指标 | Prometheus 格式文本 |

### 9.2 监控指标

| 指标 | 类型 | 标签 | 说明 |
|------|------|------|------|
| `http_requests_total` | Counter | method, path, status | HTTP 请求总数 |
| `http_request_duration_seconds` | Histogram | method, path | 请求延迟分布 |
| `http_requests_active` | Gauge | — | 当前活跃请求数 |
| `http_errors_total` | Counter | method, path, status | 错误请求计数 |
| `llm_requests_total` | Counter | provider, model, result | LLM 调用计数 |
| `llm_latency_seconds` | Histogram | provider, model | LLM 调用延迟 |
| `llm_first_token_latency_seconds` | Histogram | provider, model | 首 Token 延迟（用户体验指标） |
| `llm_tokens_total` | Counter | provider, model, type | Token 消耗计数 |
| `llm_fallback_total` | Counter | from_provider, to_provider | 降级切换计数 |
| `retrieval_latency_seconds` | Histogram | type | 检索步骤延迟 |
| `pipeline_chunks_processed` | Histogram | stage | Pipeline 各阶段 Chunk 数 |

### 9.3 OpenTelemetry 链路追踪

如需启用分布式追踪，配置 OTLP 导出端点：

```bash
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=rag-service
```

不配置 endpoint 时，Span 仅在进程内生成，不发送到外部 Collector。

---

## 10. 运维检查清单

### 10.1 部署前检查

- [ ] `.env` 文件已从 `.env.example` 创建并修改
- [ ] JWT secret 已替换为随机字符串
- [ ] 数据库密码已修改
- [ ] CORS 已配置为实际域名
- [ ] GPU 驱动已安装且 `nvidia-smi` 正常（如需加速嵌入/重排）
- [ ] Docker Compose 基础设施已启动并健康
- [ ] LLM API Key 已配置且网络可达
- [ ] 防火墙已开放必要端口

### 10.2 部署后验证

- [ ] `curl http://localhost:3000` — 前端可访问
- [ ] `curl http://localhost:8080/health` — 网关正常
- [ ] `curl http://localhost:8001/health` — RAG 服务正常
- [ ] `curl http://localhost:8001/health/llm` — LLM 连接正常
- [ ] 上传测试文档并确认索引完成
- [ ] 发起测试问答并验证流式输出

### 10.3 日常巡检

- [ ] GPU 显存使用率（`nvidia-smi`）
- [ ] Milvus 集合状态（`docker compose logs milvus`）
- [ ] Redis 内存使用（`redis-cli info memory`）
- [ ] PostgreSQL 慢查询日志
- [ ] 应用日志错误率

### 10.4 告警阈值建议

| 指标 | 阈值 | 动作 |
|------|------|------|
| CPU 使用率 | > 80% | 检查是否有资源泄露或需要扩容 |
| 检索命中率 | < 70% | 检查知识库内容质量 |
| GPU 显存 | > 90% | 检查嵌入/重排模型是否需要扩容 |
| 答案空回复率 | > 5% | 检查 LLM/Pipeline 异常 |
| LLM 降级次数/小时 | > 10 | 检查主模型健康状态 |
| Worker 积压消息 | > 100 | 扩展 Worker 副本数 |

---

## 11. 常见问题

### Q: RAG 服务启动失败，报错 `Connection refused`?

**原因**: 基础设施（PostgreSQL/Redis）未就绪。
**解决**: 先确保 `docker compose ps` 中所有服务显示为 `Up` 状态。

### Q: 上传文档后索引状态一直是 `processing`?

**原因**: Worker 未启动或 Redis 连接失败。
**解决**: 启动 Worker: `python -m workers.document_worker`。检查 Redis 连接: `redis-cli -a <password> ping`。

### Q: 问答时一直 loading，没有响应？

**原因**: LLM API 不可用或网络超时。
**解决**: 检查 `GET /health/llm` 端点。检查 API Key 是否有效、网络是否可达。如果是配置了内网 vLLM 服务器，检查 GPU 服务器状态。

### Q: 多副本部署后文档索引重复？

**原因**: 多个 Worker 消费同一 Stream 时，老版本的 `BackgroundTasks` 模式在多个副本间竞争。
**解决**: 本项目已使用 Redis Streams 消费者组，确保所有 Worker 使用相同的 **group name**（`GROUP_DOC_WORKERS`），Redis 内部会负载均衡。

### Q: 嵌入/重排序模型 OOM（显存不足）？

**解决措施**:
1. 将嵌入模型和重排序模型移至 CPU 推理（设置 `EMBEDDING_DEVICE=cpu`, `RERANKER_DEVICE=cpu`）
2. 使用更小的嵌入模型（如 `shibing624/text2vec-base-chinese`，默认即为该模型）
3. 减少批处理大小

---

> 文档版本: v1.0.1 | 更新日期: 2026-06-06
> 如有问题请提交 Issue 或联系系统管理员。
