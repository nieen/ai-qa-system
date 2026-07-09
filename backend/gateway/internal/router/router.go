package router

import (
	swaggerFiles "github.com/swaggo/files"
	ginSwagger "github.com/swaggo/gin-swagger"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/ai-qa-system/gateway/internal/handler"
	"github.com/ai-qa-system/gateway/internal/middleware"
	"github.com/ai-qa-system/gateway/internal/proxy"
	"github.com/ai-qa-system/gateway/internal/repository"
	"github.com/ai-qa-system/gateway/internal/service"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// RegisterRoutes 注册所有 API 路由
// 负责组装依赖（Repository → Service → Proxy → Handler）并注册路由
func RegisterRoutes(r *gin.Engine, cfg *config.Config, logger *zap.SugaredLogger) *handler.Handler {
	// ---- 仓储层 ----
	userRepo := repository.NewUserRepository()
	auditRepo := repository.NewAuditRepository()
	statsRepo := repository.NewStatsRepository()
	piplRepo := repository.NewPIPLRepository()

	// ---- 服务层 ----
	authSvc := service.NewAuthService(cfg, userRepo, auditRepo)
	userSvc := service.NewUserService(userRepo, auditRepo, piplRepo)
	adminSvc := service.NewAdminService(userRepo, auditRepo, statsRepo, piplRepo)

	// ---- 代理层 ----
	ragProxy := proxy.NewRAGProxyClient(cfg, logger)

	// 将 RAG API 能力注入服务层（用于级联删除 RAG 所属数据等跨服务操作）
	userSvc.SetRAGAPI(ragProxy.RAGAPIBaseURL(), ragProxy.HTTPClient())

	// ---- 处理层 ----
	h := handler.NewHandler(authSvc, userSvc, adminSvc, ragProxy, logger)

	auth := middleware.Authenticate(cfg.JWT.Secret)
	admin := middleware.AdminRequired()

	// ---- 公开端点 (无需认证) ----
	public := r.Group("/api/v1")
	{
		public.POST("/auth/login", h.Login)
		public.POST("/auth/register", h.Register)
	}

	// ---- Swagger 文档 ----
	r.GET("/swagger/*any", ginSwagger.WrapHandler(swaggerFiles.Handler))

	// ---- 需要认证的端点 ----
	protected := r.Group("/api/v1")
	protected.Use(auth)
	{
		// 用户管理
		protected.GET("/user/profile", h.GetProfile)
		protected.PUT("/user/profile", h.UpdateProfile)
		protected.POST("/user/logout", h.Logout)

		// 数据合规 (PIPL)
		protected.GET("/user/export", h.ExportData)
		protected.POST("/user/delete-request", h.RequestDeletion)
		protected.POST("/user/delete-request/:requestId/confirm", h.ConfirmDeletion)
		protected.POST("/user/delete-request/:requestId/cancel", h.CancelDeletion)

		// 知识库 (使用通用 Forward，无需单独 handler)
		protected.GET("/knowledge-bases", h.Forward("GET", "/knowledge-bases"))
		protected.POST("/knowledge-bases", h.Forward("POST", "/knowledge-bases"))
		protected.GET("/knowledge-bases/:id", h.Forward("GET", "/knowledge-bases/:id"))
		protected.PUT("/knowledge-bases/:id", h.Forward("PUT", "/knowledge-bases/:id"))
		protected.DELETE("/knowledge-bases/:id", h.Forward("DELETE", "/knowledge-bases/:id"))

		// 文档管理
		protected.GET("/knowledge-bases/:kbId/documents", h.Forward("GET", "/knowledge-bases/:kbId/documents"))
		protected.POST("/knowledge-bases/:kbId/documents/upload", h.UploadDocument)
		protected.POST("/knowledge-bases/:kbId/documents/webpage", h.Forward("POST", "/knowledge-bases/:kbId/documents/webpage"))
		protected.DELETE("/knowledge-bases/:kbId/documents/:docId", h.Forward("DELETE", "/knowledge-bases/:kbId/documents/:docId"))
		protected.GET("/knowledge-bases/:kbId/documents/:docId/status", h.Forward("GET", "/knowledge-bases/:kbId/documents/:docId/status"))

		// 问答 & 消息
		protected.POST("/knowledge-bases/:kbId/chat", h.Chat)
		protected.GET("/conversations/:convId/messages", h.Forward("GET", "/conversations/:convId/messages"))

		// 对话管理
		protected.GET("/conversations", h.ForwardWithUserID("GET", "/users/{userID}/conversations"))
		protected.DELETE("/conversations/:convId", h.Forward("DELETE", "/conversations/:convId"))

		// 管理员端点
		protected.GET("/admin/stats", admin, h.GetSystemStats)
		protected.GET("/admin/users", admin, h.ListUsers)
		protected.PUT("/admin/users/:userId", admin, h.UpdateUserRole)
		protected.GET("/admin/audit-logs", admin, h.GetAuditLogs)
		protected.POST("/admin/cleanup", admin, h.AdminCleanup)
	}

	// ---- RAG 服务内部路由 (服务间调用) ----
	internal := r.Group("/internal/api/v1")
	{
		internal.GET("/health", h.InternalHealth)
	}

	logger.Infof("已注册 %d 个路由端点", len(r.Routes()))
	return h
}
