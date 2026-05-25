#!/bin/bash
# ============================================
# 企业 AI 智能问答系统 - 一键启动脚本
# ============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "======================================"
echo "  企业 AI 智能问答系统 - 一键启动"
echo "======================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 检查命令
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}[错误] 未找到命令: $1${NC}"
        echo "请先安装 $1"
        exit 1
    fi
}

echo -e "${BLUE}[1/5] 检查环境依赖...${NC}"
check_command docker
check_command docker-compose
check_command python3
check_command node
check_command go

echo -e "${GREEN}    环境检查通过${NC}"

# 步骤 1: 启动基础设施
echo ""
echo -e "${BLUE}[2/5] 启动基础设施 (Milvus + PostgreSQL + Redis + MinIO)...${NC}"
cd "$SCRIPT_DIR/infra"
if docker-compose ps 2>/dev/null | grep -q "Up"; then
    echo -e "${YELLOW}    基础设施已在运行中${NC}"
else
    docker-compose up -d
    echo -e "${GREEN}    基础设施启动完成${NC}"
    
    # 等待服务就绪
    echo -e "${YELLOW}    等待数据库就绪...${NC}"
    sleep 10
fi

# 步骤 2: 启动 RAG 服务
echo ""
echo -e "${BLUE}[3/5] 启动 RAG 服务...${NC}"
cd "$PROJECT_DIR/backend/rag-service"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}    创建 Python 虚拟环境...${NC}"
    python3 -m venv venv
fi

source venv/bin/activate
if [ ! -f ".env" ]; then
    cp "$PROJECT_DIR/.env.example" ".env"
    echo -e "${YELLOW}    已创建 .env 文件，请根据需要修改配置${NC}"
fi

# 检查依赖
if [ ! -f "venv/installed.flag" ]; then
    echo -e "${YELLOW}    安装 Python 依赖...${NC}"
    pip install -r requirements.txt -q
    touch venv/installed.flag
    echo -e "${GREEN}    依赖安装完成${NC}"
fi

# 启动 RAG 服务 (后台)
if lsof -i:8001 &>/dev/null; then
    echo -e "${YELLOW}    RAG 服务已在运行 (端口 8001)${NC}"
else
    nohup python -m app.main > rag-service.log 2>&1 &
    RAG_PID=$!
    echo -e "${GREEN}    RAG 服务已启动 (PID: $RAG_PID, 端口: 8001)${NC}"
    sleep 3
fi
deactivate

# 步骤 3: 启动 API 网关
echo ""
echo -e "${BLUE}[4/5] 启动 Go API 网关...${NC}"
cd "$PROJECT_DIR/backend/gateway"

if [ ! -f "go.sum" ]; then
    echo -e "${YELLOW}    下载 Go 依赖...${NC}"
    go mod tidy
fi

if lsof -i:8080 &>/dev/null; then
    echo -e "${YELLOW}    API 网关已在运行 (端口 8080)${NC}"
else
    nohup go run cmd/main.go > gateway.log 2>&1 &
    GW_PID=$!
    echo -e "${GREEN}    API 网关已启动 (PID: $GW_PID, 端口: 8080)${NC}"
    sleep 2
fi

# 步骤 4: 启动前端
echo ""
echo -e "${BLUE}[5/5] 启动前端界面...${NC}"
cd "$PROJECT_DIR/frontend/ai-qa-app"

if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}    安装前端依赖...${NC}"
    npm install --silent
fi

if [ ! -f ".env.local" ]; then
    echo "NEXT_PUBLIC_API_BASE=http://localhost:8080/api/v1" > .env.local
fi

# 前端在后台构建并运行
npm run dev > frontend.log 2>&1 &
FE_PID=$!
echo -e "${GREEN}    前端已启动 (PID: $FE_PID, 地址: http://localhost:3000)${NC}"

# 显示总结
echo ""
echo "======================================"
echo -e "${GREEN}  系统启动完成！${NC}"
echo "======================================"
echo ""
echo "  前端界面:     http://localhost:3000"
echo "  API 网关:     http://localhost:8080"
echo "  RAG 服务:     http://localhost:8001"
echo "  Milvus 控制台: http://localhost:9091"
echo "  MinIO 控制台:  http://localhost:9001"
echo ""
echo "  默认管理员账号: admin / admin123"
echo ""
echo "  日志文件:"
echo "    RAG 服务: backend/rag-service/rag-service.log"
echo "    API 网关: backend/gateway/gateway.log"
echo "    前端:     frontend/ai-qa-app/frontend.log"
echo ""
echo "  停止服务: 请手动 kill 对应进程"
echo "======================================"
