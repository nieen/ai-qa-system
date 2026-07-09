#!/usr/bin/env bash
# ============================================================
# ai-qa-system — 一键部署脚本
# 用法: bash deploy/local-deploy.sh
#
# 流程:
#   1. git pull 拉取最新代码
#   2. Docker Compose 启动全部基础设施
#   3. 等待所有服务就绪（轮询等待）
#   4. 执行数据库迁移
#   5. 构建并启动所有应用容器
#   6. 健康检查确认服务可用
# ============================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# ───────────────────────────────────────────────────
# 颜色输出
# ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ───────────────────────────────────────────────────
# Step 1 — 拉取最新代码
# ───────────────────────────────────────────────────
info "====== 步骤 1/6: 拉取最新代码 ======"
git pull
success "代码已更新"

# ───────────────────────────────────────────────────
# Step 2 — 启动基础设施
# ───────────────────────────────────────────────────
info "====== 步骤 2/6: 启动基础设施 ======"
docker compose -f deploy/infra/docker-compose.yml up -d
success "基础设施已启动"

# ───────────────────────────────────────────────────
# Step 3 — 等待服务就绪
# ───────────────────────────────────────────────────
info "====== 步骤 3/6: 等待服务就绪 ======"

wait_for_health() {
    local name="$1"
    local url="$2"
    local max_retries="$3"
    local retries=0

    while [ $retries -lt "$max_retries" ]; do
        if curl -sf "$url" > /dev/null 2>&1; then
            success "$name 就绪"
            return 0
        fi
        retries=$((retries + 1))
        sleep 3
    done
    warn "$name 未在预期时间内就绪，继续尝试部署..."
    return 1
}

info "等待 PostgreSQL..."
docker compose -f deploy/infra/docker-compose.yml exec -T postgres pg_isready -U aiqa 2>/dev/null && \
    success "PostgreSQL 就绪" || sleep 10

info "等待 Redis..."
docker compose -f deploy/infra/docker-compose.yml exec -T redis redis-cli -a aiqa_redis_pass_2026 ping 2>/dev/null | grep -q PONG && \
    success "Redis 就绪" || sleep 5

info "等待 Milvus..."
wait_for_health "Milvus" "http://localhost:9091/health" 30

# ───────────────────────────────────────────────────
# Step 4 — 执行数据库迁移
# ───────────────────────────────────────────────────
info "====== 步骤 4/6: 执行数据库迁移 ======"

info "运行统一迁移..."
cd "$PROJECT_ROOT/backend/gateway" && go run ./cmd/migrate/ up 2>&1
success "数据库迁移完成"

# ───────────────────────────────────────────────────
# Step 5 — 构建并启动应用
# ───────────────────────────────────────────────────
info "====== 步骤 5/6: 构建并启动应用 ======"

# 检查是否有 app compose 文件
APP_COMPOSE=""
if [ -f "deploy/docker/docker-compose.app.yml" ]; then
    APP_COMPOSE="-f deploy/docker/docker-compose.app.yml"
fi

docker compose -f deploy/infra/docker-compose.yml $APP_COMPOSE up -d --build 2>&1 | tail -3
success "应用已启动"

# ───────────────────────────────────────────────────
# Step 6 — 健康检查
# ───────────────────────────────────────────────────
info "====== 步骤 6/6: 健康检查 ======"

sleep 5

echo ""
info "检查服务状态..."
echo ""

services=(
    "Go 网关|http://localhost:8080/health"
    "RAG 服务|http://localhost:8001/health"
)

all_ok=true
for entry in "${services[@]}"; do
    name="${entry%%|*}"
    url="${entry##*|}"
    if curl -sf "$url" > /dev/null 2>&1; then
        success "✅ $name → $url"
    else
        warn "❌ $name → $url (未就绪)"
        all_ok=false
    fi
done

echo ""
if [ "$all_ok" = true ]; then
    success "╔══════════════════════════════════════════╗"
    success "║  部署完成！                              ║"
    success "╚══════════════════════════════════════════╝"
    echo ""
    info "  前端:  http://localhost:3000"
    info "  API:   http://localhost:8080"
    info "  RAG:   http://localhost:8001/docs"
    info "  Swagger: http://localhost:8080/swagger/index.html"
else
    warn "部分服务未就绪，请检查日志:"
    info "  docker compose -f deploy/infra/docker-compose.yml logs -f"
fi
echo ""
