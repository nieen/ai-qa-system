package handler

import (
	"strings"

	"github.com/ai-qa-system/gateway/internal/proxy"
	"github.com/ai-qa-system/gateway/internal/service"
	"github.com/gin-gonic/gin"
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

// replacePathParam 将路径模板中的 :key 路径段替换为实际值。
// 基于路径段精确匹配（而非子串替换），避免 :id 与 :ids 这类前缀冲突导致的路径污染。
func replacePathParam(pathTemplate, key, value string) string {
	token := ":" + key
	segments := strings.Split(pathTemplate, "/")
	for i, seg := range segments {
		if seg == token {
			segments[i] = value
		}
	}
	return strings.Join(segments, "/")
}

// appendQuery 将原始请求的查询串透传到目标路径，避免代理丢失 ?page=&size= 等参数。
func appendQuery(c *gin.Context, path string) string {
	if q := c.Request.URL.RawQuery; q != "" {
		path += "?" + q
	}
	return path
}

// Forward 创建一个通用代理 handler，将匹配 :param 的 Gin 路径参数自动替换到目标路径。
// 示例: Forward("GET", "/knowledge-bases/:id") → Gin 路由 /knowledge-bases/:id
// 会将 :id 替换为实际值后代理到 RAG 服务，并透传原始查询串。
func (h *Handler) Forward(method, pathTemplate string) gin.HandlerFunc {
	return func(c *gin.Context) {
		path := pathTemplate
		for _, p := range c.Params {
			path = replacePathParam(path, p.Key, p.Value)
		}
		path = appendQuery(c, path)
		h.ragProxy.Request(c, method, path, nil)
	}
}

// ForwardWithUserID 同 Forward，但在 URL 中用 userID 替换 {userID} 占位符。
// 适用于 RAG 路由需要 /users/{userID}/... 模式的场景。
func (h *Handler) ForwardWithUserID(method, pathTemplate string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := c.GetString(ctxKeyUserID)
		path := strings.ReplaceAll(pathTemplate, "{userID}", userID)
		for _, p := range c.Params {
			path = replacePathParam(path, p.Key, p.Value)
		}
		path = appendQuery(c, path)
		h.ragProxy.Request(c, method, path, nil)
	}
}
