package handler

import (
	"fmt"
	"net/http"

	"github.com/gin-gonic/gin"
)

// ==================== 知识库 ====================

// ListKnowledgeBases 获取知识库列表
// @Summary     获取知识库列表
// @Tags        知识库
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "知识库列表"
// @Router      /knowledge-bases [get]
func (h *Handler) ListKnowledgeBases(c *gin.Context) {
	h.ragProxy.Request(c, "GET", "/knowledge-bases", nil)
}

// CreateKnowledgeBase 创建知识库
// @Summary     创建知识库
// @Tags        知识库
// @Security    BearerAuth
// @Router      /knowledge-bases [post]
func (h *Handler) CreateKnowledgeBase(c *gin.Context) {
	h.ragProxy.Request(c, "POST", "/knowledge-bases", nil)
}

// GetKnowledgeBase 获取知识库详情
// @Summary     获取知识库详情
// @Tags        知识库
// @Security    BearerAuth
// @Router      /knowledge-bases/{id} [get]
func (h *Handler) GetKnowledgeBase(c *gin.Context) {
	id := c.Param("id")
	h.ragProxy.Request(c, "GET", fmt.Sprintf("/knowledge-bases/%s", id), nil)
}

// UpdateKnowledgeBase 更新知识库
// @Summary     更新知识库
// @Tags        知识库
// @Security    BearerAuth
// @Router      /knowledge-bases/{id} [put]
func (h *Handler) UpdateKnowledgeBase(c *gin.Context) {
	id := c.Param("id")
	h.ragProxy.Request(c, "PUT", fmt.Sprintf("/knowledge-bases/%s", id), nil)
}

// DeleteKnowledgeBase 删除知识库
// @Summary     删除知识库
// @Tags        知识库
// @Security    BearerAuth
// @Router      /knowledge-bases/{id} [delete]
func (h *Handler) DeleteKnowledgeBase(c *gin.Context) {
	id := c.Param("id")
	h.ragProxy.Request(c, "DELETE", fmt.Sprintf("/knowledge-bases/%s", id), nil)
}

// ==================== 文档 ====================

// ListDocuments 获取文档列表
// @Summary     获取文档列表
// @Tags        文档管理
// @Security    BearerAuth
// @Router      /knowledge-bases/{kbId}/documents [get]
func (h *Handler) ListDocuments(c *gin.Context) {
	kbID := c.Param("kbId")
	h.ragProxy.Request(c, "GET", fmt.Sprintf("/knowledge-bases/%s/documents", kbID), nil)
}

// UploadDocument 上传文档
// @Summary     上传文档
// @Description 上传文档到知识库（代理到 RAG 服务）
// @Tags        文档管理
// @Security    BearerAuth
// @Router      /knowledge-bases/{kbId}/documents/upload [post]
func (h *Handler) UploadDocument(c *gin.Context) {
	kbID := c.Param("kbId")

	maxSize := int64(50 << 20) // 默认 50MB
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxSize)

	h.ragProxy.UploadFile(c, kbID)
}

// AddWebPage 添加网页
// @Summary     添加网页
// @Tags        文档管理
// @Security    BearerAuth
// @Router      /knowledge-bases/{kbId}/documents/webpage [post]
func (h *Handler) AddWebPage(c *gin.Context) {
	kbID := c.Param("kbId")
	h.ragProxy.Request(c, "POST", fmt.Sprintf("/knowledge-bases/%s/documents/webpage", kbID), nil)
}

// DeleteDocument 删除文档
// @Summary     删除文档
// @Tags        文档管理
// @Security    BearerAuth
// @Router      /knowledge-bases/{kbId}/documents/{docId} [delete]
func (h *Handler) DeleteDocument(c *gin.Context) {
	kbID := c.Param("kbId")
	docID := c.Param("docId")
	h.ragProxy.Request(c, "DELETE", fmt.Sprintf("/knowledge-bases/%s/documents/%s", kbID, docID), nil)
}

// GetDocumentStatus 获取文档索引状态
// @Summary     获取文档索引状态
// @Tags        文档管理
// @Security    BearerAuth
// @Router      /knowledge-bases/{kbId}/documents/{docId}/status [get]
func (h *Handler) GetDocumentStatus(c *gin.Context) {
	kbID := c.Param("kbId")
	docID := c.Param("docId")
	h.ragProxy.Request(c, "GET", fmt.Sprintf("/knowledge-bases/%s/documents/%s/status", kbID, docID), nil)
}

// ==================== 问答 ====================

// Chat 知识库问答 (SSE 流式)
// @Summary     知识库问答
// @Description 发送问题进行知识库问答，返回 SSE 流式响应
// @Tags        问答
// @Accept      json
// @Produce     text/event-stream
// @Security    BearerAuth
// @Param       kbId path string true "知识库 ID"
// @Success     200 {string} string "SSE 事件流"
// @Router      /knowledge-bases/{kbId}/chat [post]
func (h *Handler) Chat(c *gin.Context) {
	kbID := c.Param("kbId")
	userID := c.GetString(ctxKeyUserID)

	var req map[string]interface{}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "无效的请求参数", "code": "INVALID_PARAMS"})
		return
	}
	req["user_id"] = userID

	h.ragProxy.RequestStream(c, "POST", fmt.Sprintf("/knowledge-bases/%s/chat", kbID), req)
}

// GetMessages 获取对话消息
// @Summary     获取对话消息
// @Tags        问答
// @Security    BearerAuth
// @Router      /conversations/{convId}/messages [get]
func (h *Handler) GetMessages(c *gin.Context) {
	convID := c.Param("convId")
	h.ragProxy.Request(c, "GET", fmt.Sprintf("/conversations/%s/messages", convID), nil)
}

// ==================== 对话 ====================

// ListConversations 获取对话列表
// @Summary     获取对话列表
// @Tags        对话管理
// @Security    BearerAuth
// @Router      /conversations [get]
func (h *Handler) ListConversations(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	h.ragProxy.Request(c, "GET", fmt.Sprintf("/users/%s/conversations", userID), nil)
}

// DeleteConversation 删除对话
// @Summary     删除对话
// @Tags        对话管理
// @Security    BearerAuth
// @Router      /conversations/{convId} [delete]
func (h *Handler) DeleteConversation(c *gin.Context) {
	convID := c.Param("convId")
	h.ragProxy.Request(c, "DELETE", fmt.Sprintf("/conversations/%s", convID), nil)
}

// ==================== 健康检查 ====================

// InternalHealth 内部健康检查
// @Summary     内部健康检查
// @Description RAG 服务间健康检查
// @Tags        运维
// @Success     200 {object} map[string]interface{} "健康"
// @Router      /internal/api/v1/health [get]
func (h *Handler) InternalHealth(c *gin.Context) {
	c.JSON(200, gin.H{"status": "ok"})
}

// CheckDownstreamHealth 检查下游 RAG 服务健康
// @Summary     下游健康检查
// @Description 检查 RAG 服务是否可用
// @Tags        运维
// @Success     200 {object} map[string]interface{} "下游服务健康状态"
// @Router      /health/downstream [get]
func (h *Handler) CheckDownstreamHealth(c *gin.Context) {
	h.ragProxy.CheckHealth(c)
}
