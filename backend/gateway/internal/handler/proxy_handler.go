package handler

import (
	"fmt"
	"net/http"

	"github.com/gin-gonic/gin"
)

// ==================== 知识库 ====================

// 知识库 CRUD 通过 h.Forward() 在 router.go 中注册，无需单独 handler。

// ==================== 文档管理 ====================

// UploadDocument 上传文档（特殊 handler：需要处理文件上传 + 大小限制）
// @Summary     上传文档
// @Tags        文档管理
// @Security    BearerAuth
// @Router      /knowledge-bases/{kbId}/documents/upload [post]
func (h *Handler) UploadDocument(c *gin.Context) {
	kbID := c.Param("kbId")
	maxSize := int64(50 << 20)
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxSize)
	h.ragProxy.UploadFile(c, kbID)
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

// 以下知识库/文档路由通过 h.Forward() 在 router.go 中统一注册:
//   GET    /knowledge-bases                        → Forward("GET", "/knowledge-bases")
//   POST   /knowledge-bases                        → Forward("POST", "/knowledge-bases")
//   GET    /knowledge-bases/:id                     → Forward("GET", "/knowledge-bases/:id")
//   PUT    /knowledge-bases/:id                     → Forward("PUT", "/knowledge-bases/:id")
//   DELETE /knowledge-bases/:id                     → Forward("DELETE", "/knowledge-bases/:id")
//   GET    /knowledge-bases/:kbId/documents          → Forward("GET", "/knowledge-bases/:kbId/documents")
//   POST   /knowledge-bases/:kbId/documents/webpage  → Forward("POST", "/knowledge-bases/:kbId/documents/webpage")
//   DELETE /knowledge-bases/:kbId/documents/:docId   → Forward("DELETE", "/knowledge-bases/:kbId/documents/:docId")
//   GET    /knowledge-bases/:kbId/documents/:docId/status → Forward("GET", "/knowledge-bases/:kbId/documents/:docId/status")
//   GET    /conversations/:convId/messages            → Forward("GET", "/conversations/:convId/messages")
//   DELETE /conversations/:convId                     → Forward("DELETE", "/conversations/:convId")
