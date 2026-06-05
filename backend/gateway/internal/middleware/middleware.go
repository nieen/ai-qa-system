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
)

// 上下文键常量 (与 handler 保持一致)
const (
	ContextKeyUserID    = "user_id"
	ContextKeyUserRole  = "user_role"
	ContextKeyUsername  = "username"
	ContextKeyRequestID = "request_id"
)

// ==================== 日志记录器 ====================
// middleware 包内部使用的 logger，由 InitLogger 设置

var (
	logger   *zap.SugaredLogger
	loggerMu sync.Mutex
)

// SetLogger 设置 middleware 包使用的 Logger
func SetLogger(l *zap.SugaredLogger) {
	loggerMu.Lock()
	defer loggerMu.Unlock()
	logger = l
}

// getLogger 获取 Logger（懒初始化兜底）
func getLogger() *zap.SugaredLogger {
	loggerMu.Lock()
	defer loggerMu.Unlock()
	if logger == nil {
		l, _ := zap.NewProduction()
		logger = l.Sugar()
	}
	return logger
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
		return redisRateLimiter(cfg)
	default:
		return localRateLimiter(cfg)
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
