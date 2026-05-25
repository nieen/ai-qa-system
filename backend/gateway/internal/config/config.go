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
	Secret       string `yaml:"secret"`
	ExpiryHours  int    `yaml:"expiry_hours"`
}

// RateLimitConfig 限流配置
type RateLimitConfig struct {
	Enabled          bool    `yaml:"enabled"`
	RequestsPerSecond float64 `yaml:"requests_per_second"`
	Burst            int     `yaml:"burst"`
}

// ServicesConfig 后端服务配置
type ServicesConfig struct {
	RAGService  ServiceEndpoint `yaml:"rag_service"`
	LLMService  ServiceEndpoint `yaml:"llm_service"`
}

// ServiceEndpoint 服务端点
type ServiceEndpoint struct {
	BaseURL    string `yaml:"base_url"`
	Timeout    time.Duration `yaml:"timeout"`
	RetryCount int    `yaml:"retry_count"`
}

// CORSConfig CORS 配置
type CORSConfig struct {
	AllowedOrigins []string `yaml:"allowed_origins"`
	AllowedMethods []string `yaml:"allowed_methods"`
	AllowedHeaders []string `yaml:"allowed_headers"`
}

// Load 从文件加载配置
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
	if cfg.Log.Level == "" {
		cfg.Log.Level = "info"
	}

	return cfg, nil
}
