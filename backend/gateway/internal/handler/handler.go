package handler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// Handler API 处理器
type Handler struct {
	cfg    *config.Config
	logger *zap.SugaredLogger
	client *http.Client
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
	// 代理到 RAG 服务进行认证
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
	userID := c.GetString("user_id")
	h.proxyToRAGService(c, "GET", fmt.Sprintf("/users/%s", userID), nil)
}

func (h *Handler) UpdateProfile(c *gin.Context) {
	userID := c.GetString("user_id")
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
	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(400, gin.H{"error": "请上传文件", "code": "FILE_REQUIRED"})
		return
	}
	defer file.Close()

	// 将上传的文件转发到 RAG 服务
	ragURL := fmt.Sprintf("%s/api/v1/knowledge-bases/%s/documents/upload", h.cfg.Services.RAGService.BaseURL, kbID)
	req, err := http.NewRequest("POST", ragURL, file)
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}
	req.Header.Set("Content-Type", header.Header.Get("Content-Type"))
	req.Header.Set("X-User-ID", c.GetString("user_id"))

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
	userID := c.GetString("user_id")

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
	userID := c.GetString("user_id")
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

// ==================== 内部辅助方法 ====================

// proxyToRAGService 将请求代理到 RAG 服务
func (h *Handler) proxyToRAGService(c *gin.Context, method, path string, body interface{}) {
	ragURL := h.cfg.Services.RAGService.BaseURL + "/api/v1" + path

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

	// 如果 body 为 nil 但请求方法需要 body，传递原始请求 body
	if body == nil && (method == "POST" || method == "PUT") {
		reqBody = c.Request.Body
	}

	req, err := http.NewRequest(method, ragURL, reqBody)
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}

	// 传递用户信息
	req.Header.Set("X-User-ID", c.GetString("user_id"))
	req.Header.Set("X-User-Role", c.GetString("user_role"))
	req.Header.Set("X-Request-ID", c.GetString("request_id"))
	req.Header.Set("Content-Type", "application/json")

	resp, err := h.client.Do(req)
	if err != nil {
		h.logger.Errorf("RAG 服务请求失败: %v", err)
		c.JSON(502, gin.H{"error": "服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}
	defer resp.Body.Close()

	bodyBytes, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, resp.Header.Get("Content-Type"), bodyBytes)
}

// proxyToRAGServiceStream 流式代理到 RAG 服务
func (h *Handler) proxyToRAGServiceStream(c *gin.Context, method, path string, body interface{}) {
	ragURL := h.cfg.Services.RAGService.BaseURL + "/api/v1" + path

	jsonData, err := json.Marshal(body)
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}

	req, err := http.NewRequest(method, ragURL, bytes.NewReader(jsonData))
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}

	req.Header.Set("X-User-ID", c.GetString("user_id"))
	req.Header.Set("X-Request-ID", c.GetString("request_id"))
	req.Header.Set("Content-Type", "application/json")

	resp, err := h.client.Do(req)
	if err != nil {
		c.JSON(502, gin.H{"error": "服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}
	defer resp.Body.Close()

	// 流式转发响应
	c.Status(resp.StatusCode)
	for k, v := range resp.Header {
		for _, hv := range v {
			c.Header(k, hv)
		}
	}
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")

	io.Copy(c.Writer, resp.Body)
}
