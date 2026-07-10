package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

const usage = `统一数据库迁移入口

用法:
  migrate up                    执行全部待处理迁移
  migrate down                  回滚最近一次迁移
  migrate status                查看迁移状态
  migrate new gateway <name>    创建新的网关迁移文件
  migrate new rag <name>        创建新的 RAG 迁移文件

环境变量:
  GATEWAY_DSN   网关数据库 DSN (默认: postgres://aiqa:***@localhost:5432/aiqa_gateway?sslmode=disable)
  RAG_DSN       RAG 数据库 DSN  (默认: postgresql+asyncpg://aiqa:***@localhost:5432/aiqa_rag)
  MIGRATE_IMAGE golang-migrate Docker 镜像 (默认: migrate/migrate:v4.18.1)
`

var (
	gatewayDSN    = envOrDefault("GATEWAY_DSN", "postgres://aiqa:aiqa_secure_pass_2026@localhost:5432/aiqa_gateway?sslmode=disable")
	migrateImage  = envOrDefault("MIGRATE_IMAGE", "migrate/migrate:v4.18.1")
	projectRoot   = findProjectRoot()
	migrationsDir = filepath.Join(projectRoot, "deploy", "infra", "migrations")
)

func main() {
	if len(os.Args) < 2 {
		fmt.Print(usage)
		os.Exit(1)
	}

	switch os.Args[1] {
	case "up":
		runGatewayMigrate("up")
		runRAGAlembic("upgrade", "head")

	case "down":
		// 网关回滚 1 步
		runGatewayMigrate("down", "1")
		// RAG 回滚 1 步
		runRAGAlembic("downgrade", "-1")

	case "status":
		runGatewayMigrate("version")
		runRAGAlembic("current")

	case "new":
		if len(os.Args) < 4 {
			fmt.Println("用法: migrate new <gateway|rag> <迁移名称>")
			os.Exit(1)
		}
		db := os.Args[2]
		name := os.Args[3]
		switch db {
		case "gateway":
			createGatewayMigration(name)
		case "rag":
			createRAGMigration(name)
		default:
			fmt.Fprintf(os.Stderr, "未知数据库类型: %s (可用: gateway, rag)\n", db)
			os.Exit(1)
		}

	case "help", "--help", "-h":
		fmt.Print(usage)

	default:
		fmt.Fprintf(os.Stderr, "未知命令: %s\n\n", os.Args[1])
		fmt.Print(usage)
		os.Exit(1)
	}
}

// ───────────────────────────────────────────────────
// Gateway: 通过 Docker 运行 golang-migrate
// ───────────────────────────────────────────────────

func runGatewayMigrate(args ...string) {
	fmt.Println("━━━ 网关迁移 (golang-migrate) ━━━")
	// 拼接所有参数
	cmdArgs := []string{
		"run", "--rm",
		"-v", migrationsDir + "/gateway:/migrations",
		migrateImage,
		"-path=/migrations",
		"-database=" + gatewayDSN,
	}
	cmdArgs = append(cmdArgs, args...)

	cmd := exec.Command("docker", cmdArgs...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "⚠️  网关迁移失败: %v\n", err)
		fmt.Println("   确保 Docker 已运行且 Postgres 可访问")
		return
	}
	fmt.Println("✅ 网关迁移完成")
}

// ───────────────────────────────────────────────────
// RAG: 通过子进程运行 alembic
// ───────────────────────────────────────────────────

func runRAGAlembic(args ...string) {
	fmt.Println("━━━ RAG 迁移 (Alembic) ━━━")
	ragServiceDir := filepath.Join(projectRoot, "backend", "rag-service")
	alembicCfg := filepath.Join(projectRoot, "deploy", "infra", "migrations", "rag", "alembic.ini")

	cmdArgs := append([]string{"-c", alembicCfg}, args...)
	cmd := exec.Command("alembic", cmdArgs...)
	cmd.Dir = ragServiceDir
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "⚠️  RAG 迁移失败: %v\n", err)
		fmt.Println("   确保 alembic 已安装 (pip install alembic)")
		return
	}
	fmt.Println("✅ RAG 迁移完成")
}

// ───────────────────────────────────────────────────
// 创建新的迁移文件
// ───────────────────────────────────────────────────

func createGatewayMigration(name string) {
	dir := filepath.Join(migrationsDir, "gateway")
	ts := timestamp()

	up := filepath.Join(dir, fmt.Sprintf("%s_%s.up.sql", ts, name))
	down := filepath.Join(dir, fmt.Sprintf("%s_%s.down.sql", ts, name))

	for _, p := range []string{up, down} {
		if err := os.WriteFile(p, []byte("-- " + filepath.Base(p) + "\n\n"), 0644); err != nil {
			fmt.Fprintf(os.Stderr, "创建文件失败 %s: %v\n", p, err)
			os.Exit(1)
		}
	}
	fmt.Printf("✅ 创建网关迁移:\n   %s\n   %s\n", up, down)
}

func createRAGMigration(name string) {
	ragServiceDir := filepath.Join(projectRoot, "backend", "rag-service")
	alembicCfg := filepath.Join(projectRoot, "deploy", "infra", "migrations", "rag", "alembic.ini")

	cmd := exec.Command("alembic", "-c", alembicCfg, "revision", "-m", name)
	cmd.Dir = ragServiceDir
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "创建 RAG 迁移失败: %v\n", err)
		fmt.Println("   确保 alembic 已安装且 RAG 依赖已配置")
		os.Exit(1)
	}
}

// ───────────────────────────────────────────────────
// 工具函数
// ───────────────────────────────────────────────────

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func findProjectRoot() string {
	// 从当前目录或二进制所在目录向上找 .git 目录
	dir, _ := os.Getwd()
	for {
		if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			// 兜底：回到 CWD
			cwd, _ := os.Getwd()
			return cwd
		}
		dir = parent
	}
}

func timestamp() string {
	// 格式: 20260709_142530
	out, err := exec.Command("date", "+%Y%m%d_%H%M%S").Output()
	if err != nil {
		return "000000_000000"
	}
	return strings.TrimSpace(string(out))
}
