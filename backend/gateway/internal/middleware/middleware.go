package middleware

import (
	"fmt"
	"sync"
	"time"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"go.uber.org/zap"
	"golang.org/x/time/rate"
)

// 上下文键常量 (与 handler 保持一致)
const (
	ContextKeyUserID    = "user_id"
	ContextKeyUserRole  = "user_role"
	ContextKeyUsername  = "username"
	ContextKeyRequestID = "request_id"
)

// ==================== Token 黑名单（吊销）====================

var (
	tokenBlacklist   = make(map[string]time.Time)
	tokenBlackMu     sync.RWMutex
	blacklistCleanup time.Duration = 1 * time.Hour
)

// init 定期清理过期黑名单条目
func init() {
	go func() {
		for {
			time.Sleep(blacklistCleanup)
			tokenBlackMu.Lock()
			now := time.Now()
			for token, expiresAt := range tokenBlacklist {
				if now.After(expiresAt) {
					delete(tokenBlacklist, token)
				}
			}
			tokenBlackMu.Unlock()
		}
	}()
}

// RevokeToken 将令牌加入黑名单
func RevokeToken(token string, expiresAt time.Time) {
	tokenBlackMu.Lock()
	defer tokenBlackMu.Unlock()
	tokenBlacklist[token] = expiresAt
}

// isTokenRevoked 检查令牌是否已被吊销
func isTokenRevoked(token string) bool {
	tokenBlackMu.RLock()
	defer tokenBlackMu.RUnlock()
	_, exists := tokenBlacklist[token]
	return exists
}

// RequestID 为每个请求注入唯一 ID
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		requestID := c.GetHeader("X-Request-ID")
		if requestID == "" {
			requestID = uuid.New().String()
		}
		c.Set(ContextKeyRequestID, requestID)
		c.Header("X-Request-ID", requestID)
		c.Next()
	}
}

// Logging 请求日志中间件
func Logging(logger *zap.SugaredLogger) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path
		query := c.Request.URL.RawQuery

		c.Next()

		latency := time.Since(start)
		statusCode := c.Writer.Status()
		requestID, _ := c.Get(ContextKeyRequestID)

		logger.Infow("API 请求",
			"request_id", requestID,
			"method", c.Request.Method,
			"path", path,
			"query", query,
			"status", statusCode,
			"latency_ms", latency.Milliseconds(),
			"client_ip", c.ClientIP(),
			"user_agent", c.Request.UserAgent(),
		)
	}
}

// CORS 跨域中间件
func CORS(cfg config.CORSConfig) gin.HandlerFunc {
	return cors.New(cors.Config{
		AllowOrigins:     cfg.AllowedOrigins,
		AllowMethods:     cfg.AllowedMethods,
		AllowHeaders:     cfg.AllowedHeaders,
		AllowCredentials: true,
		MaxAge:           12 * time.Hour,
	})
}

// RateLimiter 限流中间件 (支持 local 和 redis 两种模式)
func RateLimiter(cfg config.RateLimitConfig) gin.HandlerFunc {
	if !cfg.Enabled {
		return func(c *gin.Context) { c.Next() }
	}

	switch cfg.Type {
	case "redis":
		// 分布式限流: 使用 Redis 滑动窗口
		return redisRateLimiter(cfg)
	default:
		// 本地限流: 内存令牌桶
		return localRateLimiter(cfg)
	}
}

// localRateLimiter 本地内存令牌桶限流 (单实例)
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

// redisRateLimiter 基于 Redis 的分布式限流
func redisRateLimiter(cfg config.RateLimitConfig) gin.HandlerFunc {
	// 使用内存 + IP 分桶近似模拟分布式限流
	// 多副本部署时，建议替换为 Redis Lua 脚本
	var mu sync.Mutex
	visitors := make(map[string]*rate.Limiter)

	return func(c *gin.Context) {
		ip := c.ClientIP()

		mu.Lock()
		limiter, exists := visitors[ip]
		if !exists {
			limiter = rate.NewLimiter(rate.Limit(cfg.RequestsPerSecond), cfg.Burst)
			visitors[ip] = limiter
		}
		mu.Unlock()

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

// Authenticate JWT 认证中间件
func Authenticate(secret string) gin.HandlerFunc {
	return func(c *gin.Context) {
		token := c.GetHeader("Authorization")
		if token == "" {
			c.JSON(401, gin.H{
				"error": "缺少认证令牌",
				"code":  "MISSING_TOKEN",
			})
			c.Abort()
			return
		}

		// 去除 "Bearer " 前缀
		if len(token) > 7 && token[:7] == "Bearer " {
			token = token[7:]
		}

		// 检查 Token 是否已被吊销（登出）
		if isTokenRevoked(token) {
			c.JSON(401, gin.H{
				"error": "令牌已失效，请重新登录",
				"code":  "TOKEN_REVOKED",
			})
			c.Abort()
			return
		}

		claims, err := ValidateJWT(token, secret)
		if err != nil {
			c.JSON(401, gin.H{
				"error": fmt.Sprintf("认证失败: %v", err),
				"code":  "INVALID_TOKEN",
			})
			c.Abort()
			return
		}

		// 将用户信息注入上下文
		c.Set(ContextKeyUserID, claims.UserID)
		c.Set(ContextKeyUserRole, claims.Role)
		c.Set(ContextKeyUsername, claims.Username)
		c.Next()
	}
}

// AdminRequired 管理员权限中间件
func AdminRequired() gin.HandlerFunc {
	return func(c *gin.Context) {
		role, exists := c.Get(ContextKeyUserRole)
		if !exists || role.(string) != "admin" {
			c.JSON(403, gin.H{
				"error": "无权限执行此操作",
				"code":  "FORBIDDEN",
			})
			c.Abort()
			return
		}
		c.Next()
	}
}
