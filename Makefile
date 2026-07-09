# ============================================================
# 企业 AI 智能问答系统 — Makefile
# 统一开发/构建/部署/测试入口
# 技术栈: Go (网关) + Python (RAG) + TypeScript (前端)
# ============================================================

.PHONY: help infra up down dev dev/gateway dev/rag dev/frontend \
        build build/gateway build/frontend \
        db-migrate test test/gateway test/rag test/frontend \
        logs logs/gateway logs/rag logs/frontend \
        deploy clean reset install-deps

# ───────────────────────────────────────────────────
# Help
# ───────────────────────────────────────────────────
help:  ## 显示帮助信息
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║   AI QA System — 开发运维命令                  ║"
	@echo "╚══════════════════════════════════════════════╝"
	@echo ""
	@echo "── 基础设施 ──"
	@echo "  make infra       启动全部基础设施 (PostgreSQL/Redis/Milvus/MinIO)"
	@echo "  make infra/down  停止全部基础设施"
	@echo ""
	@echo "── 开发 (热重载) ──"
	@echo "  make dev         一键启动全部服务 (基础设施 + 网关 + RAG + 前端)"
	@echo "  make dev/gateway 仅启动 Go 网关 (air 热重载)"
	@echo "  make dev/rag     仅启动 RAG 服务 (uvicorn --reload)"
	@echo "  make dev/frontend 仅启动前端 (npm run dev)"
	@echo ""
	@echo "── 构建 ──"
	@echo "  make build           构建全部"
	@echo "  make build/gateway   编译 Go 网关"
	@echo "  make build/frontend  构建前端"
	@echo ""
	@echo "── 数据库 ──"
	@echo "  make db-migrate 执行全部数据库迁移"
	@echo ""
	@echo "── 测试 ──"
	@echo "  make test           运行全部测试"
	@echo "  make test/gateway   运行 Go 网关测试"
	@echo "  make test/rag       运行 RAG 测试"
	@echo "  make test/frontend  运行前端测试"
	@echo ""
	@echo "── 运维 ──"
	@echo "  make logs            查看所有容器日志"
	@echo "  make logs/gateway    查看网关日志"
	@echo "  make logs/rag        查看 RAG 日志"
	@echo "  make logs/frontend   查看前端日志"
	@echo ""
	@echo "── 部署 ──"
	@echo "  make deploy    一键部署 (git pull + infra + migrate + build + up)"
	@echo ""
	@echo "── 维护 ──"
	@echo "  make clean     清理构建产物"
	@echo "  make reset     重置开发环境 (down -v + up + migrate)"
	@echo ""

# ───────────────────────────────────────────────────
# 基础设施 (Docker)
# ───────────────────────────────────────────────────
infra:  ## 启动全部基础设施 (PostgreSQL/Redis/Milvus/MinIO)
	docker compose -f deploy/infra/docker-compose.yml up -d
	@echo "⏳ 等待数据库就绪..."
	@sleep 5

infra/down:  ## 停止基础设施
	docker compose -f deploy/infra/docker-compose.yml down

# ───────────────────────────────────────────────────
# 开发 (热重载)
# ───────────────────────────────────────────────────
dev/gateway:  ## 启动 Go 网关 (air 热重载)
	@echo "🚀 启动 Go 网关 (air 热重载) → :8080"
	cd backend/gateway && air -c .air.toml

dev/rag:  ## 启动 RAG 服务 (uvicorn 热重载)
	@echo "🚀 启动 RAG 服务 → :8001"
	cd backend/rag-service && uvicorn app.main:app --reload --host 0.0.0.0 --port $(or $(APP_PORT),8001)

dev/frontend:  ## 启动前端 (Next.js 热重载)
	@echo "🚀 启动前端 → :3000"
	cd frontend/ai-qa-app && npm run dev

dev:  ## 一键启动全部 (基础设施 + 三个服务)
	@echo "╔══════════════════════════════════════════╗"
	@echo "║  一键启动开发环境                         ║"
	@echo "╚══════════════════════════════════════════╝"
	$(MAKE) infra
	@echo ""
	@echo "📌 请在三个终端分别运行:"
	@echo "   make dev/gateway   → http://localhost:8080"
	@echo "   make dev/rag       → http://localhost:8001"
	@echo "   make dev/frontend  → http://localhost:3000"

# ───────────────────────────────────────────────────
# 构建
# ───────────────────────────────────────────────────
build/gateway:  ## 编译 Go 网关
	@echo "🔨 编译 Go 网关..."
	cd backend/gateway && go build -o bin/gateway ./cmd/main.go
	@echo "✅ 编译完成: backend/gateway/bin/gateway"

build/frontend:  ## 构建前端
	@echo "🔨 构建前端..."
	cd frontend/ai-qa-app && npm run build
	@echo "✅ 前端构建完成"

build: build/gateway build/frontend  ## 构建全部

# ───────────────────────────────────────────────────
# 数据库迁移
# ───────────────────────────────────────────────────
db-migrate:  ## 执行全部数据库迁移（统一入口）
	@echo "📦 统一数据库迁移入口"
	cd backend/gateway && go run ./cmd/migrate/ up

# ───────────────────────────────────────────────────
# 测试
# ───────────────────────────────────────────────────
test/gateway:  ## 运行 Go 网关测试
	cd backend/gateway && go test -v -count=1 ./...

test/rag:  ## 运行 RAG 测试
	cd backend/rag-service && python -m pytest -v

test/frontend:  ## 运行前端测试
	cd frontend/ai-qa-app && npx vitest run

test: test/gateway test/rag test/frontend  ## 运行全部测试

# ───────────────────────────────────────────────────
# 日志
# ───────────────────────────────────────────────────
logs:  ## 查看所有容器日志 (tail -f)
	docker compose -f deploy/infra/docker-compose.yml -f deploy/docker/docker-compose.app.yml logs -f 2>/dev/null || \
	docker compose -f deploy/infra/docker-compose.yml logs -f

logs/gateway:  ## 查看网关日志
	docker compose -f deploy/infra/docker-compose.yml -f deploy/docker/docker-compose.app.yml logs -f gateway 2>/dev/null || \
	echo "⚠️  请先部署应用容器"

logs/rag:  ## 查看 RAG 日志
	docker compose -f deploy/infra/docker-compose.yml -f deploy/docker/docker-compose.app.yml logs -f rag-service 2>/dev/null || \
	echo "⚠️  请先部署应用容器"

logs/frontend:  ## 查看前端日志
	docker compose -f deploy/infra/docker-compose.yml -f deploy/docker/docker-compose.app.yml logs -f frontend 2>/dev/null || \
	echo "⚠️  请先部署应用容器"

log/search:  ## 搜索日志: make log/search QUERY="error"
	docker compose -f deploy/infra/docker-compose.yml logs --since="30m ago" 2>/dev/null | grep --color=always "$(QUERY)" || \
	echo "⚠️  未找到匹配或容器未运行"

# ───────────────────────────────────────────────────
# 部署
# ───────────────────────────────────────────────────
deploy:  ## 一键部署
	@echo "╔══════════════════════════════════════════╗"
	@echo "║  一键部署                                 ║"
	@echo "╚══════════════════════════════════════════╝"
	git pull
	$(MAKE) infra
	@echo "⏳ 等待数据库就绪... (15s)"
	sleep 15
	$(MAKE) db-migrate
	docker compose -f deploy/infra/docker-compose.yml \
	               -f deploy/docker/docker-compose.app.yml up -d --build
	@echo "⏳ 检查服务..."
	sleep 5
	@echo "✅ 部署完成!"
	@echo "   前端: http://localhost:3000"
	@echo "   API:  http://localhost:8080"
	@echo "   RAG:  http://localhost:8001/docs"

# ───────────────────────────────────────────────────
# 维护
# ───────────────────────────────────────────────────
clean:  ## 清理构建产物
	rm -rf backend/gateway/bin/
	rm -rf backend/rag-service/__pycache__/
	rm -rf frontend/ai-qa-app/.next/
	@echo "✅ 清理完成"

reset: infra/down  ## 重置开发环境
	$(MAKE) infra
	@echo "⏳ 等待数据库就绪... (15s)"
	sleep 15
	$(MAKE) db-migrate
	@echo "✅ 开发环境已重置"

install-deps:  ## 安装所有依赖
	@echo "=== Go 依赖 ==="
	cd backend/gateway && go mod tidy
	@echo "=== Python 依赖 ==="
	cd backend/rag-service && pip install -r requirements.txt
	@echo "=== 前端依赖 ==="
	cd frontend/ai-qa-app && npm install
	@echo "✅ 全部依赖安装完成"
