package middleware

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/gomodule/redigo/redis"
)

// ==================== Redis 连接管理（全局共享）====================
// 多副本部署时所有 gateway 副本共享同一个 Redis 实例，实现分布式状态共享。

var (
	redisPool   *redis.Pool
	redisMu     sync.Mutex
	redisInited bool
)

// InitRedis 初始化 Redis 连接池
func InitRedis(cfg config.RedisConfig) error {
	redisMu.Lock()
	defer redisMu.Unlock()

	if redisInited {
		return nil
	}

	addr := cfg.Addr
	if addr == "" {
		addr = "localhost:6379"
	}

	redisPool = &redis.Pool{
		MaxIdle:     cfg.PoolSize / 2,
		MaxActive:   cfg.PoolSize,
		IdleTimeout: 240 * time.Second,
		Dial: func() (redis.Conn, error) {
			conn, err := redis.Dial("tcp", addr,
				redis.DialConnectTimeout(3*time.Second),
				redis.DialReadTimeout(2*time.Second),
				redis.DialWriteTimeout(2*time.Second),
			)
			if err != nil {
				return nil, fmt.Errorf("redis 连接失败: %w", err)
			}
			if cfg.Password != "" {
				if _, err := conn.Do("AUTH", cfg.Password); err != nil {
					conn.Close()
					return nil, fmt.Errorf("redis 认证失败: %w", err)
				}
			}
			if cfg.DB > 0 {
				if _, err := conn.Do("SELECT", cfg.DB); err != nil {
					conn.Close()
					return nil, fmt.Errorf("redis 选择数据库失败: %w", err)
				}
			}
			return conn, nil
		},
		TestOnBorrow: func(c redis.Conn, t time.Time) error {
			if time.Since(t) > 10*time.Second {
				_, err := c.Do("PING")
				return err
			}
			return nil
		},
	}

	// 连通性测试
	conn := redisPool.Get()
	defer conn.Close()
	if _, err := conn.Do("PING"); err != nil {
		redisPool = nil
		return fmt.Errorf("redis ping 失败: %w", err)
	}

	redisInited = true
	return nil
}

// GetRedis 获取 Redis 连接
func GetRedis() redis.Conn {
	if redisPool == nil {
		return nil
	}
	return redisPool.Get()
}

// CloseRedis 关闭连接池
func CloseRedis() {
	redisMu.Lock()
	defer redisMu.Unlock()

	if redisPool != nil {
		redisPool.Close()
		redisPool = nil
	}
	redisInited = false
}

// RedisIsAvailable 检查 Redis 是否可用（降级检测）
func RedisIsAvailable() bool {
	if redisPool == nil {
		return false
	}
	conn := redisPool.Get()
	defer conn.Close()
	_, err := conn.Do("PING")
	return err == nil
}

// ==================== 上下文 ====================

var redisCtx = context.Background()
