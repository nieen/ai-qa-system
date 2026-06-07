package handler

import (
	"github.com/gin-gonic/gin"
)

// GetSystemStats 获取系统统计
// @Summary     获取系统统计
// @Description 返回系统整体统计数据（知识库数、文档数、用户数等）
// @Tags        管理
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "系统统计"
// @Router      /admin/stats [get]
func (h *Handler) GetSystemStats(c *gin.Context) {
	stats, err := h.adminSvc.GetSystemStats()
	if err != nil {
		c.JSON(503, gin.H{"error": "数据库服务不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}
	c.JSON(200, stats)
}

// ListUsers 获取用户列表（管理员）
// @Summary     获取用户列表
// @Description 管理员获取所有用户信息
// @Tags        管理
// @Produce     json
// @Security    BearerAuth
// @Success     200 {array} map[string]interface{} "用户列表"
// @Router      /admin/users [get]
func (h *Handler) ListUsers(c *gin.Context) {
	adminID := c.GetString(ctxKeyUserID)

	users, err := h.adminSvc.ListUsers(adminID)
	if err != nil {
		c.JSON(503, gin.H{"error": "数据库服务不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}

	c.JSON(200, users)
}

// UpdateUserRole 更新用户角色（管理员）
// @Summary     更新用户角色
// @Description 管理员修改指定用户的角色
// @Tags        管理
// @Accept      json
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "角色更新成功"
// @Router      /admin/users/{userId} [put]
func (h *Handler) UpdateUserRole(c *gin.Context) {
	adminID := c.GetString(ctxKeyUserID)
	userID := c.Param("userId")

	var req UpdateUserRoleRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "无效的请求参数", "code": "INVALID_PARAMS"})
		return
	}

	if err := h.adminSvc.UpdateUserRole(adminID, userID, req.Role, c.ClientIP(), c.Request.UserAgent()); err != nil {
		c.JSON(503, gin.H{"error": "更新失败", "code": "UPDATE_FAILED"})
		return
	}

	c.JSON(200, gin.H{"message": "角色更新成功"})
}

// GetAuditLogs 获取审计日志（管理员）
// @Summary     获取审计日志
// @Description 管理员查看操作审计日志（分页）
// @Tags        管理
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "审计日志列表"
// @Router      /admin/audit-logs [get]
func (h *Handler) GetAuditLogs(c *gin.Context) {
	adminID := c.GetString(ctxKeyUserID)

	limit := 50
	offset := 0

	logs, total, err := h.adminSvc.GetAuditLogs(limit, offset)
	if err != nil {
		c.JSON(503, gin.H{"error": "查询审计日志失败", "code": "SERVICE_UNAVAILABLE"})
		return
	}

	h.logger.Infow("管理员查看审计日志", "admin_id", adminID)

	result := make([]gin.H, 0, len(logs))
	for _, l := range logs {
		result = append(result, gin.H{
			"id":            l.ID,
			"user_id":       l.UserID,
			"action":        l.Action,
			"resource_type": l.ResourceType,
			"resource_id":   l.ResourceID,
			"ip_address":    l.IPAddress,
			"user_agent":    l.UserAgent,
			"created_at":    l.CreatedAt,
		})
	}

	c.JSON(200, gin.H{
		"logs":  result,
		"total": total,
	})
}

// AdminCleanup 管理员触发数据清理（保留策略）
// @Summary     清理过期数据
// @Description 手动触发清理过期对话和审计日志
// @Tags        管理
// @Produce     json
// @Security    BearerAuth
// @Success     200 {object} map[string]interface{} "清理结果"
// @Router      /admin/cleanup [post]
func (h *Handler) AdminCleanup(c *gin.Context) {
	adminID := c.GetString(ctxKeyUserID)
	convDays := 90
	logDays := 180

	result, err := h.adminSvc.Cleanup(adminID, c.ClientIP(), c.Request.UserAgent(), convDays, logDays)
	if err != nil {
		c.JSON(503, gin.H{"error": "清理失败", "code": "CLEANUP_FAILED"})
		return
	}

	c.JSON(200, gin.H{
		"message":                     "数据清理完成",
		"conversations_deleted":       result.ConversationsDeleted,
		"audit_logs_deleted":          result.AuditLogsDeleted,
		"conversation_retention_days": convDays,
		"audit_log_retention_days":    logDays,
	})
}
