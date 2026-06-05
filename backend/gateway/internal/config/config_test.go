package config

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLoadDefaults(t *testing.T) {
	// 创建最小配置
	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "config.yaml")
	content := []byte("server:\n  name: test\njwt:\n  secret: test-secret\n")
	if err := os.WriteFile(cfgPath, content, 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := Load(cfgPath)
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}

	if cfg.Server.Port != "8080" {
		t.Errorf("默认端口 = %q, 期望 8080", cfg.Server.Port)
	}
	if cfg.Server.Mode != "release" {
		t.Errorf("默认模式 = %q, 期望 release", cfg.Server.Mode)
	}
	if cfg.Log.Level != "info" {
		t.Errorf("默认日志级别 = %q, 期望 info", cfg.Log.Level)
	}
	if cfg.Server.MaxBodyBytes != 10<<20 {
		t.Errorf("默认 MaxBodyBytes = %d, 期望 %d", cfg.Server.MaxBodyBytes, 10<<20)
	}
	if cfg.Services.RAGService.RetryCount != 2 {
		t.Errorf("默认重试次数 = %d, 期望 2", cfg.Services.RAGService.RetryCount)
	}
}

func TestLoadFullConfig(t *testing.T) {
	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "config.yaml")
	content := []byte(`
server:
  name: ai-qa-gateway
  port: "8080"
  mode: debug
  read_timeout: 30s
  write_timeout: 60s
  max_header_bytes: 1048576
  max_body_bytes: 52428800

log:
  level: debug
  format: json
  output: stdout

database:
  dsn: postgres://test:test@localhost:5432/test
  max_open_conns: 50
  max_idle_conns: 20
  conn_max_lifetime: 30m

redis:
  addr: localhost:6379
  password: test
  db: 0
  pool_size: 50

jwt:
  secret: test-secret
  expiry_hours: 24

rate_limit:
  enabled: true
  type: local
  requests_per_second: 100
  burst: 200

services:
  rag_service:
    base_url: "http://localhost:8001"
    timeout: 120s
    retry_count: 3
    circuit_breaker:
      enabled: true
      failure_count: 5
      recovery_timeout: "30s"
      half_open_max: 3
  llm_service:
    base_url: "http://localhost:8000/v1"
    timeout: 120s

cors:
  allowed_origins:
    - "http://localhost:3000"
  allowed_methods:
    - GET
    - POST
  allowed_headers:
    - Content-Type
    - Authorization
`)
	if err := os.WriteFile(cfgPath, content, 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := Load(cfgPath)
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}

	// Server
	if cfg.Server.Name != "ai-qa-gateway" {
		t.Errorf("Name = %q", cfg.Server.Name)
	}
	if cfg.Server.ReadTimeout != 30*time.Second {
		t.Errorf("ReadTimeout = %v", cfg.Server.ReadTimeout)
	}
	if cfg.Server.MaxBodyBytes != 52428800 {
		t.Errorf("MaxBodyBytes = %d", cfg.Server.MaxBodyBytes)
	}

	// JWT
	if cfg.JWT.Secret != "test-secret" {
		t.Errorf("JWT Secret = %q", cfg.JWT.Secret)
	}

	// Services
	if cfg.Services.RAGService.BaseURL != "http://localhost:8001" {
		t.Errorf("RAG BaseURL = %q", cfg.Services.RAGService.BaseURL)
	}
	if !cfg.Services.RAGService.CircuitBreaker.Enabled {
		t.Error("CircuitBreaker 应启用")
	}
	if cfg.Services.RAGService.CircuitBreaker.FailureCount != 5 {
		t.Errorf("FailureCount = %d", cfg.Services.RAGService.CircuitBreaker.FailureCount)
	}

	// CORS
	if len(cfg.CORS.AllowedOrigins) != 1 || cfg.CORS.AllowedOrigins[0] != "http://localhost:3000" {
		t.Errorf("CORS Origins = %v", cfg.CORS.AllowedOrigins)
	}
}

func TestJWTSecretFromEnv(t *testing.T) {
	// 设置环境变量
	os.Setenv("JWT_SECRET", "env-override-secret")
	defer os.Unsetenv("JWT_SECRET")

	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "config.yaml")
	content := []byte("jwt:\n  secret: file-secret\n")
	if err := os.WriteFile(cfgPath, content, 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := Load(cfgPath)
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}

	if cfg.JWT.Secret != "env-override-secret" {
		t.Errorf("JWT Secret = %q, 期望环境变量覆盖值", cfg.JWT.Secret)
	}
}

func TestFileNotFound(t *testing.T) {
	_, err := Load("/nonexistent/config.yaml")
	if err == nil {
		t.Error("期望文件不存在的错误，但得到 nil")
	}
}
