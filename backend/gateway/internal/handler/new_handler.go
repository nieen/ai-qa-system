package handler

import (
	"github.com/ai-qa-system/gateway/internal/proxy"
	"github.com/ai-qa-system/gateway/internal/service"
	"go.uber.org/zap"
)

// 上下文键常量
const (
	ctxKeyUserID    = "user_id"
	ctxKeyUserRole  = "user_role"
	ctxKeyUsername  = "username"
	ctxKeyRequestID = "request_id"
)

// Handler slim API 处理器
// 职责仅限：HTTP 请求解析 → 调用 Service/Proxy → 返回响应
type Handler struct {
	authSvc  service.AuthService
	userSvc  service.UserService
	adminSvc service.AdminService
	ragProxy *proxy.RAGProxyClient
	logger   *zap.SugaredLogger
}

// NewHandler 创建新的处理器
// 依赖由上层（router）注入，不再自建依赖
func NewHandler(
	authSvc service.AuthService,
	userSvc service.UserService,
	adminSvc service.AdminService,
	ragProxy *proxy.RAGProxyClient,
	logger *zap.SugaredLogger,
) *Handler {
	// 将 logger 注入到 service 层
	if s, ok := authSvc.(interface{ SetLogger(*zap.SugaredLogger) }); ok {
		s.SetLogger(logger)
	}
	if s, ok := userSvc.(interface{ SetLogger(*zap.SugaredLogger) }); ok {
		s.SetLogger(logger)
	}
	if s, ok := adminSvc.(interface{ SetLogger(*zap.SugaredLogger) }); ok {
		s.SetLogger(logger)
	}

	return &Handler{
		authSvc:  authSvc,
		userSvc:  userSvc,
		adminSvc: adminSvc,
		ragProxy: ragProxy,
		logger:   logger,
	}
}
