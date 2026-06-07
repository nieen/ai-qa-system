package handler

import (
	"errors"
	"net/http"

	"github.com/ai-qa-system/gateway/internal/service"
	"github.com/gin-gonic/gin"
)

// GetProfile 获取用户信息
// @Summary     获取当前用户信息
// @Description 获取已登录用户的详细个人信息
// @Tags        用户管理
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "用户信息"
// @Failure     401 {object} map[string]interface{} "未认证"
// @Router      /user/profile [get]
func (h *Handler) GetProfile(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)

	profile, err := h.userSvc.GetProfile(userID)
	if err != nil {
		if errors.Is(err, service.ErrUserNotFound) {
			c.JSON(404, gin.H{"error": "用户不存在", "code": "USER_NOT_FOUND"})
		} else {
			c.JSON(503, gin.H{"error": "数据库服务不可用", "code": "SERVICE_UNAVAILABLE"})
		}
		return
	}

	c.JSON(200, profile)
}

// UpdateProfile 更新用户信息（预留）
// @Summary     更新用户信息
// @Tags        用户管理
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "更新成功"
// @Router      /user/profile [put]
func (h *Handler) UpdateProfile(c *gin.Context) {
	c.JSON(200, gin.H{"message": "更新成功"})
}

// ExportData 导出用户个人数据 (PIPL §45 数据可携带权)
// @Summary     导出个人数据
// @Description 导出当前用户的所有个人数据（资料、对话、文档）
// @Tags        数据合规
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "用户数据"
// @Failure     401 {object} map[string]interface{} "未认证"
// @Router      /user/export [get]
func (h *Handler) ExportData(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)

	data, err := h.userSvc.ExportData(userID)
	if err != nil {
		c.JSON(503, gin.H{"error": "数据服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}

	c.JSON(200, data)
}

// Logout 用户登出 (Token 吊销)
// @Summary     用户登出
// @Description 注销当前会话，吊销 JWT Token（经 Redis 广播到所有副本）
// @Tags        用户管理
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "登出成功"
// @Router      /user/logout [post]
func (h *Handler) Logout(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	tokenID := c.GetString("token_id") // 由 JWT 中间件注入

	_ = h.userSvc.Logout(userID, tokenID)

	h.logger.Infow("用户登出", "user_id", userID)
	c.JSON(200, gin.H{"message": "登出成功"})
}

// RequestDeletion 申请删除账户 (PIPL §47)
// @Summary     申请删除账户
// @Description 提交账户删除申请（有 7 天冷静期，7 天后自动删除）
// @Tags        数据合规
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "删除申请已提交"
// @Router      /user/delete-request [post]
func (h *Handler) RequestDeletion(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)

	requestID, err := h.userSvc.RequestDeletion(userID)
	if err != nil {
		c.JSON(503, gin.H{"error": "删除服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}

	c.JSON(200, gin.H{
		"message":    "删除申请已提交，请在 7 天内确认",
		"request_id": requestID,
	})
}

// ConfirmDeletion 确认删除账户
// @Summary     确认删除账户
// @Description 确认删除请求，立即删除账户及所有关联数据
// @Tags        数据合规
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "账户已删除"
// @Router      /user/delete-request/{requestId}/confirm [post]
func (h *Handler) ConfirmDeletion(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	requestID := c.Param("requestId")

	if err := h.userSvc.ConfirmDeletion(requestID, userID); err != nil {
		h.logger.Errorw("确认删除失败", "request_id", requestID, "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "删除失败，请稍后重试",
			"code":  "DELETE_FAILED",
		})
		return
	}

	c.JSON(200, gin.H{"message": "账户及所有关联数据已删除"})
}

// CancelDeletion 取消删除账户
// @Summary     取消删除账户
// @Description 在确认删除前取消删除申请
// @Tags        数据合规
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "删除已取消"
// @Router      /user/delete-request/{requestId}/cancel [post]
func (h *Handler) CancelDeletion(c *gin.Context) {
	userID := c.GetString(ctxKeyUserID)
	requestID := c.Param("requestId")

	if err := h.userSvc.CancelDeletion(requestID, userID); err != nil {
		h.logger.Errorw("取消删除失败", "request_id", requestID, "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "取消失败，请稍后重试",
			"code":  "CANCEL_FAILED",
		})
		return
	}

	c.JSON(200, gin.H{"message": "删除申请已取消"})
}
