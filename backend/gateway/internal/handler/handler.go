package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"math/rand"
	"net/http"
	"time"

	"github.com/ai-qa-system/gateway/internal/config"
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

// Handler API 处理器
type Handler struct {
	cfg          *config.Config
	logger       *zap.SugaredLogger
	client       *http.Client
	breakerGroup *CircuitBreakerGroup
}

// NewHandler 创建新的处理器
func NewHandler(cfg *config.Config, logger *zap.SugaredLogger) *Handler {
	return &Handler{
		cfg:    cfg,
		logger: logger,
		client: &http.Client{
			Timeout: 120 * time.Second,
			Transport: &http.Transport{
				MaxIdleConns:        100,
				MaxIdleConnsPerHost: 20,
				IdleConnTimeout:     90 * time.Second,
			},
		},
		breakerGroup: NewCircuitBreakerGroup(),
	}
}

// ==================== 认证 ====================

type LoginRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

func (h *Handler) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "无效的请求参数", "code": "INVALID_PARAMS"})
		return
	}
	h.proxyToRAGService(c, "POST", "/auth/login", req)
}

type RegisterRequest struct {
	Username    string `json:"username" binding:"required"`
	Password    string `json:"password" binding:"required,min=6"`
	DisplayName string `json:"display_name"`
	Email       string `json:"email"`
}

func (h *Handler) Register(c *gin.Context) {
	var req RegisterRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "无效的请求参数", "code": "INVALID_PARAMS"})
		return
	}
	h.proxyToRAGService(c, "POST", "/auth/register", req)
}

// ==================== 用户 ====================

func (h *Handler) GetProfile(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	h.proxyToRAGService(c, "GET", fmt.Sprintf("/users/%s", userID), nil)
}

func (h *Handler) UpdateProfile(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	h.proxyToRAGService(c, "PUT", fmt.Sprintf("/users/%s", userID), nil)
}

// ==================== 知识库 ====================

func (h *Handler) ListKnowledgeBases(c *gin.Context) {
	h.proxyToRAGService(c, "GET", "/knowledge-bases", nil)
}

func (h *Handler) CreateKnowledgeBase(c *gin.Context) {
	h.proxyToRAGService(c, "POST", "/knowledge-bases", nil)
}

func (h *Handler) GetKnowledgeBase(c *gin.Context) {
	id := c.Param("id")
	h.proxyToRAGService(c, "GET", fmt.Sprintf("/knowledge-bases/%s", id), nil)
}

func (h *Handler) UpdateKnowledgeBase(c *gin.Context) {
	id := c.Param("id")
	h.proxyToRAGService(c, "PUT", fmt.Sprintf("/knowledge-bases/%s", id), nil)
}

func (h *Handler) DeleteKnowledgeBase(c *gin.Context) {
	id := c.Param("id")
	h.proxyToRAGService(c, "DELETE", fmt.Sprintf("/knowledge-bases/%s", id), nil)
}

// ==================== 文档 ====================

func (h *Handler) ListDocuments(c *gin.Context) {
	kbID := c.Param("kbId")
	h.proxyToRAGService(c, "GET", fmt.Sprintf("/knowledge-bases/%s/documents", kbID), nil)
}

func (h *Handler) UploadDocument(c *gin.Context) {
	kbID := c.Param("kbId")

	// 限制上传文件大小
	maxSize := h.cfg.Server.MaxBodyBytes
	if maxSize <= 0 {
		maxSize = 50 << 20 // 默认 50MB
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxSize)

	file, header, err := c.Request.FormFile("file")
	if err != nil {
		if err.Error() == "http: request body too large" {
			c.JSON(413, gin.H{"error": "文件过大", "code": "FILE_TOO_LARGE"})
			return
		}
		c.JSON(400, gin.H{"error": "请上传文件", "code": "FILE_REQUIRED"})
		return
	}
	defer file.Close()

	ragURL := fmt.Sprintf("%s/api/v1/knowledge-bases/%s/documents/upload", h.cfg.Services.RAGService.BaseURL, kbID)
	req, err := http.NewRequest("POST", ragURL, file)
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}
	req.Header.Set("Content-Type", header.Header.Get("Content-Type"))
	req.Header.Set("X-User-ID", c.GetString(ctxKeyUserID))

	resp, err := h.client.Do(req)
	if err != nil {
		c.JSON(502, gin.H{"error": "服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, resp.Header.Get("Content-Type"), body)
}

func (h *Handler) AddWebPage(c *gin.Context) {
	kbID := c.Param("kbId")
	h.proxyToRAGService(c, "POST", fmt.Sprintf("/knowledge-bases/%s/documents/webpage", kbID), nil)
}

func (h *Handler) DeleteDocument(c *gin.Context) {
	kbID := c.Param("kbId")
	docID := c.Param("docId")
	h.proxyToRAGService(c, "DELETE", fmt.Sprintf("/knowledge-bases/%s/documents/%s", kbID, docID), nil)
}

func (h *Handler) GetDocumentStatus(c *gin.Context) {
	kbID := c.Param("kbId")
	docID := c.Param("docId")
	h.proxyToRAGService(c, "GET", fmt.Sprintf("/knowledge-bases/%s/documents/%s/status", kbID, docID), nil)
}

// ==================== 问答 ====================

func (h *Handler) Chat(c *gin.Context) {
	kbID := c.Param("kbId")
	userID := c.GetString(ctxKeyUserID)

	var req map[string]interface{}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "无效的请求参数", "code": "INVALID_PARAMS"})
		return
	}
	req["user_id"] = userID

	h.proxyToRAGServiceStream(c, "POST", fmt.Sprintf("/knowledge-bases/%s/chat", kbID), req)
}

func (h *Handler) GetMessages(c *gin.Context) {
	convID := c.Param("convId")
	h.proxyToRAGService(c, "GET", fmt.Sprintf("/conversations/%s/messages", convID), nil)
}

// ==================== 对话 ====================

func (h *Handler) ListConversations(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	h.proxyToRAGService(c, "GET", fmt.Sprintf("/users/%s/conversations", userID), nil)
}

func (h *Handler) DeleteConversation(c *gin.Context) {
	convID := c.Param("convId")
	h.proxyToRAGService(c, "DELETE", fmt.Sprintf("/conversations/%s", convID), nil)
}

// ==================== 管理 ====================

func (h *Handler) GetSystemStats(c *gin.Context) {
	h.proxyToRAGService(c, "GET", "/admin/stats", nil)
}

func (h *Handler) ListUsers(c *gin.Context) {
	h.proxyToRAGService(c, "GET", "/admin/users", nil)
}

func (h *Handler) UpdateUserRole(c *gin.Context) {
	userID := c.Param("userId")
	h.proxyToRAGService(c, "PUT", fmt.Sprintf("/admin/users/%s", userID), nil)
}

func (h *Handler) GetAuditLogs(c *gin.Context) {
	h.proxyToRAGService(c, "GET", "/admin/audit-logs", nil)
}

func (h *Handler) InternalHealth(c *gin.Context) {
	c.JSON(200, gin.H{"status": "ok"})
}

// ==================== 下游健康检查 ====================

// CheckDownstreamHealth 检查下游 RAG 服务健康状态
func (h *Handler) CheckDownstreamHealth(c *gin.Context) {
	ragURL := h.cfg.Services.RAGService.BaseURL + "/health"

	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "GET", ragURL, nil)
	if err != nil {
		c.JSON(503, gin.H{
			"status":  "unhealthy",
			"service": "rag-service",
			"error":   err.Error(),
		})
		return
	}

	resp, err := h.client.Do(req)
	if err != nil {
		c.JSON(503, gin.H{
			"status":  "unhealthy",
			"service": "rag-service",
			"error":   err.Error(),
		})
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, "application/json", body)
}

// ==================== 内部辅助方法 ====================

// buildRAGURL 构建 RAG 服务的完整 URL
func (h *Handler) buildRAGURL(path string) string {
	return h.cfg.Services.RAGService.BaseURL + "/api/v1" + path
}

// proxyToRAGService 将请求代理到 RAG 服务 (带熔断和重试)
func (h *Handler) proxyToRAGService(c *gin.Context, method, path string, body interface{}) {
	ragURL := h.buildRAGURL(path)

	// 熔断检查
	cb := h.getCircuitBreaker()
	if !cb.Allow() {
		h.logger.Warnw("熔断器阻止请求", "path", path, "method", method)
		c.JSON(503, gin.H{
			"error": "服务暂不可用 (熔断)",
			"code":  "CIRCUIT_OPEN",
		})
		return
	}

	// 构造请求
	var reqBody io.Reader
	if body != nil {
		jsonData, err := json.Marshal(body)
		if err != nil {
			h.logger.Errorf("JSON 序列化失败: %v", err)
			c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
			return
		}
		reqBody = bytes.NewReader(jsonData)
	}

	if body == nil && (method == "POST" || method == "PUT") {
		reqBody = c.Request.Body
	}

	// 重试逻辑
	maxRetries := h.cfg.Services.RAGService.RetryCount
	var lastErr error
	var resp *http.Response

	for attempt := 0; attempt <= maxRetries; attempt++ {
		// 上下文传递 (支持客户端断开)
		ctx := c.Request.Context()
		req, err := http.NewRequestWithContext(ctx, method, ragURL, reqBody)
		if err != nil {
			c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
			return
		}

		// 传递用户信息
		req.Header.Set("X-User-ID", c.GetString(ctxKeyUserID))
		req.Header.Set("X-User-Role", c.GetString(ctxKeyUserRole))
		req.Header.Set("X-Request-ID", c.GetString(ctxKeyRequestID))
		req.Header.Set("Content-Type", "application/json")

		resp, lastErr = h.client.Do(req)
		if lastErr == nil {
			break
		}

		// 如果是客户端断开，直接返回
		if ctx.Err() != nil {
			h.logger.Warnw("客户端断开连接", "path", path)
			return
		}

		// 重试前等待 (指数退避 + 随机抖动)
		if attempt < maxRetries {
			backoff := time.Duration(math.Pow(2, float64(attempt))) * 200 * time.Millisecond
			jitter := time.Duration(rand.Int63n(int64(backoff / 2)))
			time.Sleep(backoff + jitter)
			h.logger.Infow("重试请求",
				"attempt", attempt+1,
				"max", maxRetries,
				"path", path,
			)
		}
	}

	if lastErr != nil {
		h.logger.Errorf("RAG 服务请求失败 (已重试 %d 次): %v", maxRetries, lastErr)
		cb.Failure()
		c.JSON(502, gin.H{"error": "服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}
	defer resp.Body.Close()

	// 记录下游状态码
	if resp.StatusCode >= 500 {
		cb.Failure()
	} else {
		cb.Success()
	}

	bodyBytes, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, resp.Header.Get("Content-Type"), bodyBytes)
}

// proxyToRAGServiceStream 流式代理到 RAG 服务 (SSE)
func (h *Handler) proxyToRAGServiceStream(c *gin.Context, method, path string, body interface{}) {
	ragURL := h.buildRAGURL(path)

	// 熔断检查
	cb := h.getCircuitBreaker()
	if !cb.Allow() {
		c.JSON(503, gin.H{
			"error": "服务暂不可用 (熔断)",
			"code":  "CIRCUIT_OPEN",
		})
		return
	}

	jsonData, err := json.Marshal(body)
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}

	// 使用客户端的 context，支持客户端断开
	ctx := c.Request.Context()
	req, err := http.NewRequestWithContext(ctx, method, ragURL, bytes.NewReader(jsonData))
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}

	req.Header.Set("X-User-ID", c.GetString(ctxKeyUserID))
	req.Header.Set("X-Request-ID", c.GetString(ctxKeyRequestID))
	req.Header.Set("Content-Type", "application/json")

	resp, err := h.client.Do(req)
	if err != nil {
		// 检查是否是客户端断开导致的错误
		if ctx.Err() != nil {
			h.logger.Infow("SSE 流中断: 客户端断开", "path", path)
			return
		}
		h.logger.Errorf("SSE 代理请求失败: %v", err)
		cb.Failure()
		// 客户端可能已断开，尝试发送错误
		select {
		case <-ctx.Done():
			return
		default:
			c.JSON(502, gin.H{"error": "服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		}
		return
	}
	defer resp.Body.Close()

	// 成功获取响应流
	cb.Success()

	// 流式转发 SSE 响应
	c.Status(resp.StatusCode)
	for k, v := range resp.Header {
		for _, hv := range v {
			c.Header(k, hv)
		}
	}
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	// 使用 io.Copy 转发，同时监听客户端断开
	buf := make([]byte, 4096)
	for {
		select {
		case <-ctx.Done():
			// 客户端断开 → 停止转发
			h.logger.Infow("SSE 流终止: 客户端断开", "path", path)
			return
		default:
			n, readErr := resp.Body.Read(buf)
			if n > 0 {
				if _, writeErr := c.Writer.Write(buf[:n]); writeErr != nil {
					return
				}
				c.Writer.Flush()
			}
			if readErr != nil {
				return
			}
		}
	}
}

// getCircuitBreaker 获取或创建熔断器
func (h *Handler) getCircuitBreaker() *CircuitBreaker {
	cbCfg := h.cfg.Services.RAGService.CircuitBreaker
	if !cbCfg.Enabled {
		// 返回一个永远允许通过的熔断器
		return &CircuitBreaker{state: stateClosed}
	}

	timeout, err := time.ParseDuration(cbCfg.RecoveryTimeout)
	if err != nil {
		timeout = 30 * time.Second
	}

	return h.breakerGroup.GetOrCreate(
		"rag-service",
		cbCfg.FailureCount,
		timeout,
		cbCfg.HalfOpenMax,
	)
}
