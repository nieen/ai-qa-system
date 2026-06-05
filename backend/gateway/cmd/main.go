package main

// @title           AI QA System API
// @version         1.0.0
// @description     企业级 AI 智能问答系统 - API 网关
// @description
// @description     ## 服务架构
// @description     - **API 网关** (本服务) → 认证/限流/路由/熔断
// @description     - **RAG 服务** → 文档索引/向量检索/LLM 问答
// @description     - **PostgreSQL** → 用户/对话/审计日志
// @description     - **Redis** → 缓存/分布式限流/Token 黑名单
// @description     - **Milvus** → 向量数据库
// @description
// @description     ## 认证方式
// @description     ```
// @description     POST /api/v1/auth/login  →  获取 JWT Token
// @description     Authorization: Bearer <token>  →  访问受保护端点
// @description     ```
// @description
// @description     ## 数据合规
// @description     - 数据导出: GET /api/v1/user/export (PIPL §45)
// @description     - 删除账户: POST /api/v1/user/delete-request (PIPL §47)
// @description     - 审计日志: 所有写操作自动记录
// @termsOfService  https://github.com/nieen/ai-qa-system

// @contact.name   AI QA System Team
// @contact.url    https://github.com/nieen/ai-qa-system

// @license.name  MIT
// @license.url   https://opensource.org/licenses/MIT

// @host      localhost:8080
// @BasePath  /api/v1

// @securityDefinitions.apikey  BearerAuth
// @in                          header
// @name                        Authorization
// @description                 JWT Token (格式: Bearer \<token\>)

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/ai-qa-system/gateway/internal/database"
	"github.com/ai-qa-system/gateway/internal/middleware"
	"github.com/ai-qa-system/gateway/internal/router"

	// Swagger 文档 (go generate 生成)
	_ "github.com/ai-qa-system/gateway/docs"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

func main() {
	cfg := mustLoadConfig()
	logger := mustInitLogger(cfg.Log)
	defer logger.Sync()

	// 设置 middleware 包的日志记录器
	middleware.SetLogger(logger)

	// 初始化 Redis（用于分布式限流、Token 黑名单、熔断器）
	initRedis(cfg, logger)

	initDatabase(cfg, logger)
	r := setupRouter(cfg, logger)
	srv := createServer(cfg, r)
	startServerAsync(srv, cfg, logger)
	waitForShutdown(srv, logger)
}

// ==================== 配置 ====================

func mustLoadConfig() *config.Config {
	cfg, err := config.Load("config.yaml")
	if err != nil {
		log.Fatalf("无法加载配置: %v", err)
	}

	if cfg.JWT.Secret == "" || cfg.JWT.Secret == "change-this-to-a-secure-jwt-secret" {
		log.Printf("⚠️ 警告: JWT Secret 使用了默认值！生产环境必须通过 JWT_SECRET 环境变量设置一个复杂随机字符串。")
		if cfg.Server.Mode == "release" {
			log.Fatalf("❌ 致命错误: 生产模式禁止使用默认 JWT Secret，请设置 JWT_SECRET 环境变量")
		}
	}

	return cfg
}

// ==================== 日志 ====================

func mustInitLogger(logCfg config.LogConfig) *zap.SugaredLogger {
	logger, err := initLogger(logCfg)
	if err != nil {
		log.Fatalf("无法初始化日志: %v", err)
	}
	return logger
}

func initLogger(cfg config.LogConfig) (*zap.SugaredLogger, error) {
	var zapCfg zap.Config
	if cfg.Format == "json" {
		zapCfg = zap.NewProductionConfig()
	} else {
		zapCfg = zap.NewDevelopmentConfig()
	}

	level := zap.InfoLevel
	switch cfg.Level {
	case "debug":
		level = zap.DebugLevel
	case "info":
		level = zap.InfoLevel
	case "warn":
		level = zap.WarnLevel
	case "error":
		level = zap.ErrorLevel
	}
	zapCfg.Level.SetLevel(level)

	logger, err := zapCfg.Build()
	if err != nil {
		return nil, err
	}
	return logger.Sugar(), nil
}

// ==================== 基础设施 ====================

func initDatabase(cfg *config.Config, logger *zap.SugaredLogger) {
	gin.SetMode(cfg.Server.Mode)

	if err := database.Connect(cfg.Database); err != nil {
		logger.Warnw("数据库连接失败，认证功能将不可用", "error", err)
		return
	}
	logger.Infow("数据库连接成功", "dsn", cfg.Database.DSN)

	// 启动审计日志自动清理 (每24小时清理一次, 保留180天)
	go startAuditLogCleanup(logger)
}

// initRedis 初始化 Redis 连接池（分布式状态共享）
func initRedis(cfg *config.Config, logger *zap.SugaredLogger) {
	if err := middleware.InitRedis(cfg.Redis); err != nil {
		logger.Warnw("Redis 连接失败，分布式功能将降级到本地模式", "error", err)
		logger.Warnw("  - Token 吊销: 仅当前副本生效（多副本部署时建议修复）")
		logger.Warnw("  - 分布式限流: 降级到本地内存限流")
		logger.Warnw("  - 分布式熔断: 降级到本地熔断器")
		return
	}
	logger.Infow("Redis 连接成功",
		"addr", cfg.Redis.Addr,
		"db", cfg.Redis.DB,
	)
}

// startAuditLogCleanup 定时清理过期审计日志和对话
func startAuditLogCleanup(logger *zap.SugaredLogger) {
	const (
		auditLogRetentionDays = 180
		convRetentionDays     = 90
		cleanupInterval       = 24 * time.Hour
	)

	for {
		next := time.Now().Truncate(cleanupInterval).Add(cleanupInterval)
		time.Sleep(time.Until(next))

		convDeleted, err := database.CleanupOldConversations(convRetentionDays)
		if err != nil {
			logger.Warnw("自动清理对话失败", "error", err)
		} else if convDeleted > 0 {
			logger.Infow("自动清理过期对话", "deleted", convDeleted, "retention_days", convRetentionDays)
		}

		logDeleted, err := database.CleanupOldAuditLogs(auditLogRetentionDays)
		if err != nil {
			logger.Warnw("自动清理审计日志失败", "error", err)
		} else if logDeleted > 0 {
			logger.Infow("自动清理过期审计日志", "deleted", logDeleted, "retention_days", auditLogRetentionDays)
		}
	}
}

// setupRouter 初始化 Gin 引擎、中间件链和全部路由
//
// 路由注册由 router.RegisterRoutes 负责，它内部创建 handler.Handler 实例
// 并返回该实例供外部使用（如注册健康检查端点）。
func setupRouter(cfg *config.Config, logger *zap.SugaredLogger) *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery())

	// 全局中间件链
	r.Use(middleware.RequestID())
	r.Use(middleware.NewMetrics().MetricsMiddleware())
	r.Use(middleware.Logging(logger))
	r.Use(middleware.CORS(cfg.CORS))
	r.Use(middleware.RateLimiter(cfg.RateLimit))

	// 注册 API 路由（返回 Handler 实例供下方端点使用）
	h := router.RegisterRoutes(r, cfg, logger)

	// 非业务端点（不归属 /api/v1）
	r.GET("/health", healthEndpoint(cfg))
	r.GET("/health/downstream", h.CheckDownstreamHealth)
	r.GET("/metrics", middleware.MetricsHandler())

	return r
}

// healthEndpoint 返回一个处理 /health 请求的 gin handler 闭包
func healthEndpoint(cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"status":  "ok",
			"service": cfg.Server.Name,
			"time":    time.Now().UTC().Format(time.RFC3339),
		})
	}
}

// ==================== HTTP 服务器 ====================

func createServer(cfg *config.Config, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:           ":" + cfg.Server.Port,
		Handler:        handler,
		ReadTimeout:    cfg.Server.ReadTimeout,
		WriteTimeout:   cfg.Server.WriteTimeout,
		MaxHeaderBytes: cfg.Server.MaxHeaderBytes,
	}
}

func startServerAsync(srv *http.Server, cfg *config.Config, logger *zap.SugaredLogger) {
	go func() {
		logger.Infof("API 网关启动于 :%s", cfg.Server.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Fatalf("服务器启动失败: %v", err)
		}
	}()
}

// ==================== 优雅关闭 ====================

func waitForShutdown(srv *http.Server, logger *zap.SugaredLogger) {
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("正在关闭服务器...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		logger.Fatalf("服务器关闭异常: %v", err)
	}
	logger.Info("服务器已安全关闭")
}
