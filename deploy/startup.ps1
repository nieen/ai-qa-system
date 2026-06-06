# ============================================
# 企业 AI 智能问答系统 - Windows 一键启动脚本
# ============================================
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  企业 AI 智能问答系统 - 一键启动" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

# 步骤 1: 启动基础设施
Write-Host "`n[1/4] 启动基础设施 (Docker)..." -ForegroundColor Blue
Set-Location "$PSScriptRoot\infra"
$infraRunning = docker-compose ps 2>$null | Select-String "Up"
if ($infraRunning) {
    Write-Host "    基础设施已在运行" -ForegroundColor Yellow
} else {
    docker-compose up -d
    Write-Host "    基础设施启动完成" -ForegroundColor Green
    Write-Host "    等待服务就绪..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}

# 步骤 2: 启动 RAG 服务
Write-Host "`n[2/4] 启动 RAG 服务..." -ForegroundColor Blue
Set-Location "$ProjectRoot\backend\rag-service"

# 检查虚拟环境
if (-not (Test-Path "venv")) {
    Write-Host "    创建 Python 虚拟环境..." -ForegroundColor Yellow
    python -m venv venv
}

# 激活虚拟环境并安装依赖
$pip = if ($IsWindows) { ".\venv\Scripts\pip" } else { "venv/bin/pip" }
$python = if ($IsWindows) { ".\venv\Scripts\python" } else { "venv/bin/python" }

if (-not (Test-Path "venv\installed.flag") -and -not (Test-Path "venv/installed.flag")) {
    Write-Host "    安装 Python 依赖..." -ForegroundColor Yellow
    & $pip install -r requirements.txt -q
    if ($IsWindows) { New-Item -Path "venv\installed.flag" -ItemType File -Force | Out-Null }
    else { New-Item -Path "venv/installed.flag" -ItemType File -Force | Out-Null }
    Write-Host "    依赖安装完成" -ForegroundColor Green
}

# 检查端口
$ragRunning = Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue
if (-not $ragRunning) {
    $ragJob = Start-Job -ScriptBlock {
        param($p, $r)
        Set-Location $r
        & $p -m app.main
    } -ArgumentList $python, $ProjectRoot
    Write-Host "    RAG 服务已启动 (端口: 8001)" -ForegroundColor Green
    $ragJob | Out-File -FilePath "$ProjectRoot\backend\rag-service\rag-service.pid"
    Start-Sleep -Seconds 3
} else {
    Write-Host "    RAG 服务已在运行" -ForegroundColor Yellow
}

# 步骤 2b: 启动文档索引 Worker
Write-Host "`n[2b/5] 启动文档索引 Worker..." -ForegroundColor Blue
Set-Location "$ProjectRoot\backend\rag-service"

$workerRunning = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "document_worker" }
if (-not $workerRunning) {
    $workerJob = Start-Job -ScriptBlock {
        param($p, $r)
        Set-Location $r
        & $p -m workers.document_worker
    } -ArgumentList $python, $ProjectRoot
    Write-Host "    文档索引 Worker 已启动" -ForegroundColor Green
    Start-Sleep -Seconds 1
} else {
    Write-Host "    Worker 已在运行" -ForegroundColor Yellow
}

# 步骤 3: 启动 Go 网关
Write-Host "`n[3/5] 启动 Go API 网关..." -ForegroundColor Blue
Set-Location "$ProjectRoot\backend\gateway"

if (-not (Test-Path "go.sum")) {
    Write-Host "    下载 Go 依赖..." -ForegroundColor Yellow
    go mod tidy
}

$gwRunning = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
if (-not $gwRunning) {
    $gwJob = Start-Job -ScriptBlock {
        param($r)
        Set-Location $r
        go run cmd/main.go
    } -ArgumentList "$ProjectRoot\backend\gateway"
    Write-Host "    API 网关已启动 (端口: 8080)" -ForegroundColor Green
    Start-Sleep -Seconds 2
} else {
    Write-Host "    API 网关已在运行" -ForegroundColor Yellow
}

# 步骤 4: 启动前端
Write-Host "`n[4/5] 启动前端界面..." -ForegroundColor Blue
Set-Location "$ProjectRoot\frontend\ai-qa-app"

if (-not (Test-Path "node_modules")) {
    Write-Host "    安装前端依赖..." -ForegroundColor Yellow
    npm install --silent
}

if (-not (Test-Path ".env.local")) {
    "NEXT_PUBLIC_API_BASE=http://localhost:8080/api/v1" | Out-File -FilePath ".env.local"
}

$feRunning = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if (-not $feRunning) {
    $feJob = Start-Job -ScriptBlock {
        param($r)
        Set-Location $r
        npm run dev
    } -ArgumentList "$ProjectRoot\frontend\ai-qa-app"
    Write-Host "    前端已启动 (地址: http://localhost:3000)" -ForegroundColor Green
} else {
    Write-Host "    前端已在运行" -ForegroundColor Yellow
}

# 显示总结
Write-Host "`n======================================" -ForegroundColor Cyan
Write-Host "  系统启动完成！" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "`n  前端界面:     http://localhost:3000"
Write-Host "  API 网关:     http://localhost:8080"
Write-Host "  RAG 服务:     http://localhost:8001"
Write-Host "  Milvus 控制台: http://localhost:9091"
Write-Host "  MinIO 控制台:  http://localhost:9001"
Write-Host "`n  默认管理员账号: admin / admin123"
Write-Host "`n  查看日志: Get-Content <文件名> -Follow"
Write-Host "  停止服务: Stop-Job <JobName>"
Write-Host "======================================" -ForegroundColor Cyan
