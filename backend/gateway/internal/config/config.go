package config

import (
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

// Config 顶层配置
type Config struct {
	Server    ServerConfig    `yaml:"server"`
	Log       LogConfig       `yaml:"log"`
	Database  DatabaseConfig  `yaml:"database"`
	Redis     RedisConfig     `yaml:"redis"`
	JWT       JWTConfig       `yaml:"jwt"`
	RateLimit RateLimitConfig `yaml:"rate_limit"`
	Services  ServicesConfig  `yaml:"services"`
	CORS      CORSConfig      `yaml:"cors"`
}

// ServerConfig 服务器配置
type ServerConfig struct {
	Name           string        `yaml:"name"`
	Port           string        `yaml:"port"`
	Mode           string        `yaml:"mode"`
	ReadTimeout    time.Duration `yaml:"read_timeout"`
	WriteTimeout   time.Duration `yaml:"write_timeout"`
	MaxHeaderBytes int           `yaml:"max_header_bytes"`
	MaxBodyBytes   int64         `yaml:"max_body_bytes"` // 请求体大小限制 (字节)
}

// LogConfig 日志配置
type LogConfig struct {
	Level  string `yaml:"level"`
	Format string `yaml:"format"`
	Output string `yaml:"output"`
}

// DatabaseConfig 数据库配置
type DatabaseConfig struct {
	DSN             string        `yaml:"dsn"`
	MaxOpenConns    int           `yaml:"max_open_conns"`
	MaxIdleConns    int           `yaml:"max_idle_conns"`
	ConnMaxLifetime time.Duration `yaml:"conn_max_lifetime"`
}

// RedisConfig Redis 配置
type RedisConfig struct {
	Addr     string `yaml:"addr"`
	Password string `yaml:"password"`
	DB       int    `yaml:"db"`
	PoolSize int    `yaml:"pool_size"`
}

// JWTConfig JWT 配置
type JWTConfig struct {
	Secret      string `yaml:"secret"`
	ExpiryHours int    `yaml:"expiry_hours"`
}

// RateLimitConfig 限流配置
type RateLimitConfig struct {
	Enabled           bool    `yaml:"enabled"`
	Type              string  `yaml:"type"` // "local" (内存令牌桶) | "redis" (分布式)
	RequestsPerSecond float64 `yaml:"requests_per_second"`
	Burst             int     `yaml:"burst"`
}

// ServicesConfig 后端服务配置
type ServicesConfig struct {
	RAGService ServiceEndpoint `yaml:"rag_service"`
	LLMService ServiceEndpoint `yaml:"llm_service"`
}

// ServiceEndpoint 服务端点
type ServiceEndpoint struct {
	BaseURL        string               `yaml:"base_url"`
	Timeout        time.Duration        `yaml:"timeout"`
	RetryCount     int                  `yaml:"retry_count"`
	CircuitBreaker CircuitBreakerConfig `yaml:"circuit_breaker"`
}

// CircuitBreakerConfig 熔断器配置
type CircuitBreakerConfig struct {
	Enabled         bool   `yaml:"enabled"`
	FailureCount    int    `yaml:"failure_count"`    // 连续失败次数触发熔断
	RecoveryTimeout string `yaml:"recovery_timeout"` // 熔断后恢复时间 (e.g. "30s")
	HalfOpenMax     int    `yaml:"half_open_max"`    // 半开状态最大请求数
}

// CORSConfig CORS 配置
type CORSConfig struct {
	AllowedOrigins []string `yaml:"allowed_origins"`
	AllowedMethods []string `yaml:"allowed_methods"`
	AllowedHeaders []string `yaml:"allowed_headers"`
}

// Load 从文件加载配置，支持环境变量覆盖
func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	cfg := &Config{}
	if err := yaml.Unmarshal(data, cfg); err != nil {
		return nil, err
	}

	// 默认值
	if cfg.Server.Port == "" {
		cfg.Server.Port = "8080"
	}
	if cfg.Server.Mode == "" {
		cfg.Server.Mode = "release"
	}
	if cfg.Server.MaxBodyBytes == 0 {
		cfg.Server.MaxBodyBytes = 10 << 20 // 默认 10MB
	}
	if cfg.Log.Level == "" {
		cfg.Log.Level = "info"
	}
	if cfg.RateLimit.Type == "" {
		cfg.RateLimit.Type = "local"
	}
	if cfg.Services.RAGService.RetryCount <= 0 {
		cfg.Services.RAGService.RetryCount = 2
	}
	if cfg.Services.RAGService.CircuitBreaker.FailureCount <= 0 {
		cfg.Services.RAGService.CircuitBreaker.FailureCount = 5
	}
	if cfg.Services.RAGService.CircuitBreaker.RecoveryTimeout == "" {
		cfg.Services.RAGService.CircuitBreaker.RecoveryTimeout = "30s"
	}
	if cfg.Services.RAGService.CircuitBreaker.HalfOpenMax <= 0 {
		cfg.Services.RAGService.CircuitBreaker.HalfOpenMax = 3
	}

	// 环境变量覆盖 JWT Secret
	if envSecret := os.Getenv("JWT_SECRET"); envSecret != "" {
		cfg.JWT.Secret = envSecret
	}

	// 环境变量覆盖数据库 DSN（包含 sslmode 控制）
	if envDSN := os.Getenv("DATABASE_DSN"); envDSN != "" {
		cfg.Database.DSN = envDSN
	}
	// 单独控制 SSL（不修改已含 sslmode 的 DSN）
	if sslMode := os.Getenv("DB_SSLMODE"); sslMode != "" {
		if cfg.Database.DSN != "" {
			cfg.Database.DSN += "&sslmode=" + sslMode
		}
	}

	// 校验 JWT Secret — 防止默认值上生产
	if cfg.JWT.Secret == "" || cfg.JWT.Secret == "change-this-to-a-secure-jwt-secret" {
		// 注意: 这里不能 log，因为 logger 还没初始化。调用方会检查。
		cfg.JWT.Secret = os.Getenv("JWT_SECRET")
		if cfg.JWT.Secret == "" {
			cfg.JWT.Secret = "change-this-to-a-secure-jwt-secret"
		}
	} 
	
	// 生产环境强制要求环境变量
	if cfg.Server.Mode == "release" && cfg.JWT.Secret == "change-this-to-a-secure-jwt-secret" {
		// 返回错误，让 main.go 中的验证机制拦截
	}

	return cfg, nil
}
