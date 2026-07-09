#!/usr/bin/env bash
# ============================================================
# 企业 AI 智能问答系统 — 开发运维命令脚本 (for Git Bash / Linux)
# 等价于 make，用法: bash make.sh <command>
# ============================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

help() {
    cat <<'EOF'
╔══════════════════════════════════════════════════╗
║   AI QA System — 开发运维命令                      ║
╚══════════════════════════════════════════════════╝

── 基础设施 ──
  bash make.sh infra          启动全部基础设施
  bash make.sh infra-down     停止全部基础设施

── 开发 (热重载) ──
  bash make.sh dev            一键启动全部服务 (启动基础设施后提示)
  bash make.sh dev-gateway    启动 Go 网关 (air 热重载)
  bash make.sh dev-rag        启动 RAG 服务 (uvicorn --reload)
  bash make.sh dev-frontend   启动前端 (npm run dev)

── 构建 ──
  bash make.sh build          构建全部
  bash make.sh build-gateway  编译 Go 网关
  bash make.sh build-frontend 构建前端

── 数据库 ──
  bash make.sh db-migrate     执行全部数据库迁移

── 测试 ──
  bash make.sh test           运行全部测试
  bash make.sh test-gateway   运行 Go 网关测试
  bash make.sh test-rag       运行 RAG 测试
  bash make.sh test-frontend  运行前端测试

── 运维 ──
  bash make.sh logs           查看所有容器日志
  bash make.sh logs-gateway   查看网关日志
  bash make.sh logs-rag       查看 RAG 日志

── 部署 ──
  bash make.sh deploy         一键部署

── 维护 ──
  bash make.sh clean          清理构建产物
  bash make.sh reset          重置开发环境
  bash make.sh install-deps   安装所有依赖
EOF
}

# ───────────────────────────────────────────────────
# 基础设施
# ───────────────────────────────────────────────────
infra() {
    echo "🚀 启动基础设施..."
    docker compose -f "$PROJECT_ROOT/deploy/infra/docker-compose.yml" up -d
    echo "⏳ 等待数据库就绪..."
    sleep 5
    echo "✅ 基础设施已启动"
}

infra-down() {
    echo "🛑 停止基础设施..."
    docker compose -f "$PROJECT_ROOT/deploy/infra/docker-compose.yml" down
    echo "✅ 基础设施已停止"
}

# ───────────────────────────────────────────────────
# 开发
# ───────────────────────────────────────────────────
dev-gateway() {
    echo "🚀 启动 Go 网关 (air 热重载) → :8080"
    cd "$PROJECT_ROOT/backend/gateway"
    air -c .air.toml
}

dev-rag() {
    local port="${APP_PORT:-8001}"
    echo "🚀 启动 RAG 服务 → :$port"
    cd "$PROJECT_ROOT/backend/rag-service"
    uvicorn app.main:app --reload --host 0.0.0.0 --port "$port"
}

dev-frontend() {
    echo "🚀 启动前端 → :3000"
    cd "$PROJECT_ROOT/frontend/ai-qa-app"
    npm run dev
}

dev() {
    echo "╔══════════════════════════════════════════╗"
    echo "║  一键启动开发环境                         ║"
    echo "╚══════════════════════════════════════════╝"
    infra
    echo ""
    echo "📌 请在三个终端分别运行:"
    echo "   bash make.sh dev-gateway  → http://localhost:8080"
    echo "   bash make.sh dev-rag      → http://localhost:8001"
    echo "   bash make.sh dev-frontend → http://localhost:3000"
}

# ───────────────────────────────────────────────────
# 构建
# ───────────────────────────────────────────────────
build-gateway() {
    echo "🔨 编译 Go 网关..."
    cd "$PROJECT_ROOT/backend/gateway"
    go build -o bin/gateway ./cmd/main.go
    echo "✅ 编译完成: backend/gateway/bin/gateway"
}

build-frontend() {
    echo "🔨 构建前端..."
    cd "$PROJECT_ROOT/frontend/ai-qa-app"
    npm run build
    echo "✅ 前端构建完成"
}

build() {
    build-gateway
    build-frontend
}

# ───────────────────────────────────────────────────
# 数据库迁移
# ───────────────────────────────────────────────────
db-migrate() {
    echo "📦 统一数据库迁移入口"
    cd "$PROJECT_ROOT/backend/gateway"
    go run ./cmd/migrate/ up
}

# ───────────────────────────────────────────────────
# 测试
# ───────────────────────────────────────────────────
test-gateway() {
    cd "$PROJECT_ROOT/backend/gateway"
    go test -v -count=1 ./...
}

test-rag() {
    cd "$PROJECT_ROOT/backend/rag-service"
    python -m pytest -v
}

test-frontend() {
    cd "$PROJECT_ROOT/frontend/ai-qa-app"
    npx vitest run
}

test() {
    test-gateway
    test-rag
    test-frontend
}

# ───────────────────────────────────────────────────
# 日志
# ───────────────────────────────────────────────────
logs() {
    local compose_files="-f $PROJECT_ROOT/deploy/infra/docker-compose.yml"
    if [ -f "$PROJECT_ROOT/deploy/docker/docker-compose.app.yml" ]; then
        compose_files="$compose_files -f $PROJECT_ROOT/deploy/docker/docker-compose.app.yml"
    fi
    docker compose $compose_files logs -f
}

logs-gateway() {
    docker compose -f "$PROJECT_ROOT/deploy/infra/docker-compose.yml" logs -f gateway 2>/dev/null || \
        echo "⚠️  请先部署应用容器"
}

logs-rag() {
    docker compose -f "$PROJECT_ROOT/deploy/infra/docker-compose.yml" logs -f rag-service 2>/dev/null || \
        echo "⚠️  请先部署应用容器"
}

log-search() {
    local query="${1:-error}"
    docker compose -f "$PROJECT_ROOT/deploy/infra/docker-compose.yml" logs --since="30m ago" 2>/dev/null | \
        grep --color=always "$query" || echo "⚠️  未找到匹配或容器未运行"
}

# ───────────────────────────────────────────────────
# 部署
# ───────────────────────────────────────────────────
deploy() {
    echo "╔══════════════════════════════════════════╗"
    echo "║  一键部署                                 ║"
    echo "╚══════════════════════════════════════════╝"
    git pull
    infra
    echo "⏳ 等待数据库就绪... (15s)"
    sleep 15
    db-migrate
    docker compose -f "$PROJECT_ROOT/deploy/infra/docker-compose.yml" \
                   -f "$PROJECT_ROOT/deploy/docker/docker-compose.app.yml" up -d --build
    echo "⏳ 检查服务..."
    sleep 5
    echo "✅ 部署完成!"
    echo "   前端: http://localhost:3000"
    echo "   API:  http://localhost:8080"
    echo "   RAG:  http://localhost:8001/docs"
}

# ───────────────────────────────────────────────────
# 维护
# ───────────────────────────────────────────────────
clean() {
    echo "🧹 清理构建产物..."
    rm -rf "$PROJECT_ROOT/backend/gateway/bin/"
    rm -rf "$PROJECT_ROOT/backend/rag-service/"__pycache__/
    rm -rf "$PROJECT_ROOT/frontend/ai-qa-app/.next/"
    echo "✅ 清理完成"
}

reset() {
    infra-down
    infra
    echo "⏳ 等待数据库就绪... (15s)"
    sleep 15
    db-migrate
    echo "✅ 开发环境已重置"
}

install-deps() {
    echo "=== Go 依赖 ==="
    cd "$PROJECT_ROOT/backend/gateway" && go mod tidy
    echo "=== Python 依赖 ==="
    cd "$PROJECT_ROOT/backend/rag-service" && pip install -r requirements.txt
    echo "=== 前端依赖 ==="
    cd "$PROJECT_ROOT/frontend/ai-qa-app" && npm install
    echo "✅ 全部依赖安装完成"
}

# ───────────────────────────────────────────────────
# 主入口
# ───────────────────────────────────────────────────
case "${1:-help}" in
    help|--help|-h)            help ;;
    infra)                     infra ;;
    infra-down)                infra-down ;;
    dev)                       dev ;;
    dev-gateway)               dev-gateway ;;
    dev-rag)                   dev-rag ;;
    dev-frontend)              dev-frontend ;;
    build)                     build ;;
    build-gateway)             build-gateway ;;
    build-frontend)            build-frontend ;;
    db-migrate)                db-migrate ;;
    test)                      test ;;
    test-gateway)              test-gateway ;;
    test-rag)                  test-rag ;;
    test-frontend)             test-frontend ;;
    logs)                      logs ;;
    logs-gateway)              logs-gateway ;;
    logs-rag)                  logs-rag ;;
    log-search)                log-search "$2" ;;
    deploy)                    deploy ;;
    clean)                     clean ;;
    reset)                     reset ;;
    install-deps)              install-deps ;;
    *)                         echo "未知命令: $1"; help; exit 1 ;;
esac
