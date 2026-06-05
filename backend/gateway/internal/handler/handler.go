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

	"golang.org/x/crypto/bcrypt"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/ai-qa-system/gateway/internal/database"
	"github.com/ai-qa-system/gateway/internal/middleware"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
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

// ==================== 认证（网关直接查询数据库）====================

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

	// 直接查询数据库验证凭据
	user, err := database.GetUserByUsername(req.Username)
	if err != nil {
		h.logger.Errorw("数据库查询用户失败", "username", req.Username, "error", err)
		c.JSON(503, gin.H{"error": "认证服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}
	if user == nil {
		c.JSON(401, gin.H{"error": "用户名或密码错误", "code": "AUTH_FAILED"})
		return
	}
	if !user.IsActive {
		c.JSON(403, gin.H{"error": "账户已被禁用", "code": "ACCOUNT_DISABLED"})
		return
	}

	// bcrypt 验证密码
	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(req.Password)); err != nil {
		c.JSON(401, gin.H{"error": "用户名或密码错误", "code": "AUTH_FAILED"})
		return
	}

	// 更新最后登录时间
	_ = database.UpdateLastLogin(user.ID)

	// 在网关层签发 JWT 令牌
	token, err := middleware.GenerateJWT(user.ID, user.Username, user.Role, h.cfg.JWT.Secret, h.cfg.JWT.ExpiryHours)
	if err != nil {
		h.logger.Errorw("JWT 签发失败", "error", err)
		c.JSON(500, gin.H{"error": "令牌签发失败", "code": "TOKEN_ERROR"})
		return
	}

	h.logger.Infow("用户登录成功",
		"user_id", user.ID,
		"username", user.Username,
		"role", user.Role,
	)

	c.JSON(200, gin.H{
		"token": token,
		"user": gin.H{
			"id":           user.ID,
			"username":     user.Username,
			"role":         user.Role,
			"display_name": user.DisplayName,
		},
	})
}

type RegisterRequest struct {
	Username              string `json:"username" binding:"required"`
	Password              string `json:"password" binding:"required,min=6"`
	DisplayName           string `json:"display_name"`
	Email                 string `json:"email"`
	AcceptedPrivacyPolicy bool   `json:"accepted_privacy_policy"`
}

func (h *Handler) Register(c *gin.Context) {
	var req RegisterRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "无效的请求参数", "code": "INVALID_PARAMS"})
		return
	}

	// PIPL 第17条: 必须取得用户同意
	if !req.AcceptedPrivacyPolicy {
		c.JSON(400, gin.H{
			"error": "请阅读并同意隐私政策",
			"code":  "PRIVACY_POLICY_REQUIRED",
		})
		return
	}

	// 检查用户名唯一性
	existing, _ := database.GetUserByUsername(req.Username)
	if existing != nil {
		c.JSON(409, gin.H{"error": "用户名已存在", "code": "USERNAME_EXISTS"})
		return
	}

	// bcrypt 哈希密码
	hashedBytes, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		h.logger.Errorw("密码哈希失败", "error", err)
		c.JSON(500, gin.H{"error": "注册服务异常", "code": "REGISTER_ERROR"})
		return
	}

	userID := uuid.New().String()
	displayName := req.DisplayName
	if displayName == "" {
		displayName = req.Username
	}

	if err := database.CreateUser(userID, req.Username, string(hashedBytes), displayName, req.Email); err != nil {
		h.logger.Errorw("创建用户失败", "error", err)
		c.JSON(500, gin.H{"error": "注册失败", "code": "REGISTER_ERROR"})
		return
	}

	// 记录隐私政策同意
	clientIP := c.ClientIP()
	_ = database.RecordConsent(userID, "privacy_policy", "v1", clientIP)

	h.logger.Infow("用户注册成功",
		"user_id", userID,
		"username", req.Username,
		"consent_recorded", true,
		"ip", clientIP,
	)

	c.JSON(200, gin.H{
		"message": "注册成功",
		"user": gin.H{
			"id":       userID,
			"username": req.Username,
		},
	})
}

// ==================== 用户管理（网关直接查询数据库）====================

func (h *Handler) GetProfile(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	user, err := database.GetUserByID(userID)
	if err != nil {
		h.logger.Errorw("查询用户失败", "user_id", userID, "error", err)
		c.JSON(503, gin.H{"error": "数据库服务不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}
	if user == nil {
		c.JSON(404, gin.H{"error": "用户不存在", "code": "USER_NOT_FOUND"})
		return
	}

	c.JSON(200, gin.H{
		"id":           user.ID,
		"username":     user.Username,
		"display_name": user.DisplayName,
		"email":        user.Email,
		"role":         user.Role,
		"is_active":    user.IsActive,
	})
}

func (h *Handler) UpdateProfile(c *gin.Context) {
	// 预留：更新用户信息
	c.JSON(200, gin.H{"message": "更新成功"})
}

// ==================== 数据合规 (PIPL) ====================

// ExportData 导出用户个人数据 (PIPL 第45条 — 数据可携带权)
func (h *Handler) ExportData(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)

	data, err := database.ExportUserData(userID)
	if err != nil {
		h.logger.Errorw("导出数据失败", "user_id", userID, "error", err)
		c.JSON(500, gin.H{"error": "数据导出失败", "code": "EXPORT_ERROR"})
		return
	}

	// 记录审计
	h.logger.Infow("用户数据导出", "user_id", userID)

	c.JSON(200, data)
}

// Logout 登出 — 将当前 Token 加入黑名单
func (h *Handler) Logout(c *gin.Context) {
	token := c.GetHeader("Authorization")
	if len(token) > 7 && token[:7] == "Bearer " {
		token = token[7:]
		// 将当前 Token 标记为已吊销，有效期到 JWT 过期时间
		// 实际开发中应从 JWT Claims 中提取 exp 时间
		expiryHours := h.cfg.JWT.ExpiryHours
		if expiryHours <= 0 {
			expiryHours = 24
		}
		expiresAt := time.Now().Add(time.Duration(expiryHours) * time.Hour)
		middleware.RevokeToken(token, expiresAt)
	}

	h.logger.Infow("用户登出",
		"user_id", c.GetString(ctxKeyUserID),
	)

	c.JSON(200, gin.H{"message": "登出成功"})
}

// RequestDeletion 请求删除账号 (PIPL 第47条 — 被遗忘权)
func (h *Handler) RequestDeletion(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)

	requestID, err := database.CreateDeletionRequest(userID)
	if err != nil {
		h.logger.Errorw("创建删除请求失败", "user_id", userID, "error", err)
		c.JSON(500, gin.H{"error": "创建删除请求失败", "code": "DELETION_ERROR"})
		return
	}

	h.logger.Infow("用户请求删除账号", "user_id", userID, "request_id", requestID)

	c.JSON(200, gin.H{
		"message":    "删除请求已创建，请在7天内确认，逾期自动取消",
		"request_id": requestID,
		"expires_in": "7天",
	})
}

// ConfirmDeletion 确认删除账号
func (h *Handler) ConfirmDeletion(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	requestID := c.Param("requestId")

	if err := database.ConfirmDeletion(requestID, userID); err != nil {
		h.logger.Errorw("确认删除失败", "user_id", userID, "error", err)
		c.JSON(400, gin.H{"error": err.Error(), "code": "CONFIRM_ERROR"})
		return
	}

	h.logger.Infow("用户账号已删除", "user_id", userID)

	c.JSON(200, gin.H{
		"message": "账号已删除，所有关联数据已清除",
	})
}

// CancelDeletion 取消删除请求
func (h *Handler) CancelDeletion(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	requestID := c.Param("requestId")

	if err := database.CancelDeletion(requestID, userID); err != nil {
		c.JSON(400, gin.H{"error": err.Error(), "code": "CANCEL_ERROR"})
		return
	}

	c.JSON(200, gin.H{"message": "删除请求已取消"})
}

// AdminCleanup 管理员触发数据保留策略清理
func (h *Handler) AdminCleanup(c *gin.Context) {
	adminID := c.GetString(ctxKeyUserID)

	convDays := 90 // 对话保留 90 天
	logDays := 180 // 审计日志保留 180 天

	convDeleted, _ := database.CleanupOldConversations(convDays)
	logDeleted, _ := database.CleanupOldAuditLogs(logDays)

	_ = database.AuditAdminAction(adminID, "admin.cleanup", "system", "",
		map[string]interface{}{
			"conversations_deleted": convDeleted,
			"audit_logs_deleted":    logDeleted,
		})

	h.logger.Infow("管理员触发数据清理",
		"admin_id", adminID,
		"conversations_deleted", convDeleted,
		"audit_logs_deleted", logDeleted,
	)

	c.JSON(200, gin.H{
		"message":                     "数据清理完成",
		"conversations_deleted":       convDeleted,
		"audit_logs_deleted":          logDeleted,
		"conversation_retention_days": convDays,
		"audit_log_retention_days":    logDays,
	})
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

	maxSize := h.cfg.Server.MaxBodyBytes
	if maxSize <= 0 {
		maxSize = 50 << 20
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

// ==================== 管理（网关直接查询数据库）====================

func (h *Handler) GetSystemStats(c *gin.Context) {
	stats, err := database.GetSystemStats()
	if err != nil {
		h.logger.Errorw("获取系统统计失败", "error", err)
		c.JSON(503, gin.H{"error": "数据库服务不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}

	c.JSON(200, gin.H{
		"total_kbs":       stats.TotalKBs,
		"total_documents": stats.TotalDocuments,
		"total_chunks":    stats.TotalChunks,
		"total_users":     stats.TotalUsers,
	})
}

func (h *Handler) ListUsers(c *gin.Context) {
	adminID := c.GetString(ctxKeyUserID)

	users, err := database.ListUsers()
	if err != nil {
		h.logger.Errorw("查询用户列表失败", "error", err)
		c.JSON(503, gin.H{"error": "数据库服务不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}

	// 审计：管理员访问用户列表
	_ = database.AuditAdminAction(adminID, "admin.list_users", "user", "", nil)

	result := make([]gin.H, 0, len(users))
	for _, u := range users {
		result = append(result, gin.H{
			"id":           u.ID,
			"username":     u.Username,
			"display_name": u.DisplayName,
			"email":        u.Email,
			"role":         u.Role,
			"is_active":    u.IsActive,
		})
	}

	c.JSON(200, gin.H{"data": result, "total": len(result)})
}

func (h *Handler) UpdateUserRole(c *gin.Context) {
	adminID := c.GetString(ctxKeyUserID)
	userID := c.Param("userId")

	var req struct {
		Role string `json:"role" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "无效的请求参数", "code": "INVALID_PARAMS"})
		return
	}

	h.logger.Infow("管理员修改用户角色",
		"admin_id", adminID,
		"target_user", userID,
		"new_role", req.Role,
	)

	// 预留：更新角色逻辑
	_ = database.AuditAdminAction(adminID, "admin.update_role", "user", userID,
		map[string]interface{}{"new_role": req.Role})

	c.JSON(200, gin.H{"message": "角色更新成功"})
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

	cb := h.getCircuitBreaker()
	if !cb.Allow() {
		h.logger.Warnw("熔断器阻止请求", "path", path, "method", method)
		c.JSON(503, gin.H{
			"error": "服务暂不可用 (熔断)",
			"code":  "CIRCUIT_OPEN",
		})
		return
	}

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

	maxRetries := h.cfg.Services.RAGService.RetryCount
	var lastErr error
	var resp *http.Response

	for attempt := 0; attempt <= maxRetries; attempt++ {
		ctx := c.Request.Context()
		req, err := http.NewRequestWithContext(ctx, method, ragURL, reqBody)
		if err != nil {
			c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
			return
		}

		req.Header.Set("X-User-ID", c.GetString(ctxKeyUserID))
		req.Header.Set("X-User-Role", c.GetString(ctxKeyUserRole))
		req.Header.Set("X-Request-ID", c.GetString(ctxKeyRequestID))
		req.Header.Set("Content-Type", "application/json")

		resp, lastErr = h.client.Do(req)
		if lastErr == nil {
			break
		}

		if ctx.Err() != nil {
			h.logger.Warnw("客户端断开连接", "path", path)
			return
		}

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
		if ctx.Err() != nil {
			h.logger.Infow("SSE 流中断: 客户端断开", "path", path)
			return
		}
		h.logger.Errorf("SSE 代理请求失败: %v", err)
		cb.Failure()
		select {
		case <-ctx.Done():
			return
		default:
			c.JSON(502, gin.H{"error": "服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		}
		return
	}
	defer resp.Body.Close()

	cb.Success()

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

	buf := make([]byte, 4096)
	for {
		select {
		case <-ctx.Done():
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
