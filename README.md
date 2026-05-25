# 企业 AI 智能问答系统

基于 **DeepSeek + RAG** 的企业级智能问答平台，纯本地私有化部署，支持 PDF/Word/网页多源知识库。

> 架构设计、技术选型、流程细节详见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

## 架构概览

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Next.js     │───▶│  Go 网关      │───▶│  RAG 服务     │
│  前端界面     │    │  认证/限流    │    │  文档索引+检索  │
└──────────────┘    └──────┬───────┘    └──────┬───────┘
                           │                    │
                    ┌──────▼───────┐    ┌──────▼───────┐
                    │  PostgreSQL  │    │  Milvus       │
                    │  元数据/用户  │    │  向量数据库    │
                    └──────────────┘    └──────────────┘
                           │                    │
                    ┌──────▼───────┐    ┌──────▼───────┐
                    │  Redis       │    │  MinIO       │
                    │  缓存/限流    │    │  文档存储     │
                    └──────────────┘    └──────────────┘
```

## 技术栈

| 组件 | 技术 |
|------|------|
| LLM | DeepSeek + vLLM (本地) |
| 嵌入/重排 | BGE-M3 + BGE-Reranker |
| 向量库 | Milvus 2.5 (分布式) |
| 后端 | Go(Gin) + Python(FastAPI) |
| 前端 | Next.js 14 + Tailwind |
| 存储 | PostgreSQL + Redis + MinIO |

## 快速开始

### 前置条件
- Docker & Docker Compose
- NVIDIA GPU + CUDA 12+ (LLM 推理)
- Python 3.10+, Node 18+, Go 1.22+

### 1. 启动基础设施
```bash
cd deploy/infra
docker compose up -d
```

### 2. 部署 DeepSeek 模型 (GPU 服务器)
```bash
docker run --gpus all \
  -v /path/to/models:/models \
  -p 8000:8000 \
  vllm/vllm-openai:latest \
  --model /models/DeepSeek-R1-Distill-Qwen-32B \
  --port 8000 --gpu-memory-utilization 0.9 \
  --tensor-parallel-size 4 --dtype bfloat16
```

### 3. 启动 RAG 服务
```bash
cd backend/rag-service
pip install -r requirements.txt
python -m app.main             # → localhost:8001
```

### 4. 启动 API 网关
```bash
cd backend/gateway
go mod tidy && go run cmd/main.go   # → localhost:8080
```

### 5. 启动前端
```bash
cd frontend/ai-qa-app
npm install && npm run dev          # → localhost:3000
```

## API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/login` | POST | 登录 |
| `/api/v1/knowledge-bases` | GET/POST | 知识库 |
| `/api/v1/knowledge-bases/:id/chat` | POST | 流式问答 (SSE) |
| `/api/v1/knowledge-bases/:kbId/documents/upload` | POST | 上传文档 |
| `/api/v1/admin/stats` | GET | 系统统计 |
| `/health` | GET | 健康检查 |

## 默认访问
- 前端: http://localhost:3000
- 管理员: admin / admin123

## 项目结构
```
ai-qa-system/
├── deploy/infra/              # Docker Compose 编排
├── backend/
│   ├── gateway/               # Go API 网关
│   └── rag-service/           # Python RAG 服务
├── frontend/ai-qa-app/        # Next.js 前端
├── ARCHITECTURE.md            # 详细架构文档
└── README.md
```

## License
MIT
