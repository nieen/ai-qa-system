package main

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

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

func main() {
	cfg := mustLoadConfig()
	logger := mustInitLogger(cfg.Log)
	defer logger.Sync()

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
