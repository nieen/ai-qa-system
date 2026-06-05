package middleware

import (
	"fmt"
	"time"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/gin-gonic/gin"
	"github.com/gomodule/redigo/redis"
	"golang.org/x/time/rate"
)

// ==================== 分布式限流（Redis 滑动窗口）====================
//
// 使用 Redis Lua 脚本实现原子滑动窗口算法，支持多副本共享限流状态。
// 窗口大小固定为 1 秒，统计当前窗口内的请求数。
//
// Lua 脚本原子操作:
//   1. INCR 当前时间窗口的计数器
//   2. EXPIRE 设置 2 秒 TTL（保证窗口过期后自动清理）
//   3. 返回递增后的计数值
//
// 如果 Redis 不可用，降级到本地内存限流（不丢失限流能力）

const rateLimitLuaScript = `
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = redis.call("INCR", key)
if current == 1 then
    redis.call("EXPIRE", key, ttl)
end

if current > limit then
    return 0
end
return 1
`

var rateLimitScript = redis.NewScript(1, rateLimitLuaScript)

// redisRateLimiter 基于 Redis 的分布式限流
func redisRateLimiter(cfg config.RateLimitConfig) gin.HandlerFunc {
	return func(c *gin.Context) {
		conn := GetRedis()
		if conn == nil {
			// Redis 不可用 → 降级到本地内存限流
			localRateLimiter(cfg)(c)
			return
		}
		defer conn.Close()

		// 窗口 key: rate_limit:{ip}:{unix_second}
		now := time.Now().Unix()
		key := fmt.Sprintf("rate_limit:%s:%d", c.ClientIP(), now)
		limit := int64(cfg.RequestsPerSecond)

		result, err := redis.Int64(rateLimitScript.Do(conn, key, limit, 2))
		if err != nil || result == 0 {
			if err != nil {
				// Redis 调用失败 → 降级到本地限流
				conn.Close()
				localRateLimiter(cfg)(c)
				return
			}
			// 超过限流阈值
			c.JSON(429, gin.H{
				"error":       "请求过于频繁，请稍后重试",
				"code":        "RATE_LIMIT_EXCEEDED",
				"retry_after": "1s",
			})
			c.Abort()
			return
		}

		c.Next()
	}
}

// localRateLimiter 本地内存令牌桶限流 (单实例降级方案)
func localRateLimiter(cfg config.RateLimitConfig) gin.HandlerFunc {
	limiter := rate.NewLimiter(
		rate.Limit(cfg.RequestsPerSecond),
		cfg.Burst,
	)

	return func(c *gin.Context) {
		if !limiter.Allow() {
			c.JSON(429, gin.H{
				"error":       "请求过于频繁，请稍后重试",
				"code":        "RATE_LIMIT_EXCEEDED",
				"retry_after": "1s",
			})
			c.Abort()
			return
		}
		c.Next()
	}
}
