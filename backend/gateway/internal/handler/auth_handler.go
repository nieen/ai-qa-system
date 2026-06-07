package handler

import (
	"errors"

	"github.com/ai-qa-system/gateway/internal/service"
	"github.com/gin-gonic/gin"
)

// Login 用户登录
// @Summary     用户登录
// @Description 验证用户名密码，返回 JWT Token
// @Tags        认证
// @Accept      json
// @Produce     json
// @Param       body body LoginRequest true "登录信息"
// @Success     200 {object} map[string]interface{} "登录成功，返回 token 和用户信息"
// @Failure     401 {object} map[string]interface{} "用户名或密码错误"
// @Failure     403 {object} map[string]interface{} "账户已被禁用"
// @Failure     502 {object} map[string]interface{} "认证服务暂不可用"
// @Router      /auth/login [post]
func (h *Handler) Login(c *gin.Context) {
	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "无效的请求参数", "code": "INVALID_PARAMS"})
		return
	}

	result, err := h.authSvc.Login(req.Username, req.Password, c.ClientIP(), c.Request.UserAgent())
	if err != nil {
		switch {
		case errors.Is(err, service.ErrUserNotFound), errors.Is(err, service.ErrWrongPassword):
			c.JSON(401, gin.H{"error": "用户名或密码错误", "code": "AUTH_FAILED"})
		case errors.Is(err, service.ErrUserDisabled):
			c.JSON(403, gin.H{"error": "账户已被禁用", "code": "ACCOUNT_DISABLED"})
		default:
			c.JSON(503, gin.H{"error": "认证服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		}
		return
	}

	c.JSON(200, gin.H{
		"token": result.Token,
		"user": gin.H{
			"id":           result.User.ID,
			"username":     result.User.Username,
			"role":         result.User.Role,
			"display_name": result.User.DisplayName,
		},
	})
}

// Register 用户注册
// @Summary     用户注册
// @Description 创建新用户，需要同意隐私政策
// @Tags        认证
// @Accept      json
// @Produce     json
// @Param       body body RegisterRequest true "注册信息"
// @Success     200 {object} map[string]interface{} "注册成功"
// @Failure     400 {object} map[string]interface{} "请求参数错误或未同意隐私政策"
// @Failure     409 {object} map[string]interface{} "用户名已存在"
// @Router      /auth/register [post]
func (h *Handler) Register(c *gin.Context) {
	var req RegisterRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "无效的请求参数", "code": "INVALID_PARAMS"})
		return
	}

	err := h.authSvc.Register(service.RegisterRequest{
		Username:              req.Username,
		Password:              req.Password,
		DisplayName:           req.DisplayName,
		Email:                 req.Email,
		ClientIP:              c.ClientIP(),
		UserAgent:             c.Request.UserAgent(),
		AcceptedPrivacyPolicy: req.AcceptedPrivacyPolicy,
	})
	if err != nil {
		switch {
		case errors.Is(err, service.ErrPrivacyRequired):
			c.JSON(400, gin.H{
				"error": "请阅读并同意隐私政策",
				"code":  "PRIVACY_POLICY_REQUIRED",
			})
		case errors.Is(err, service.ErrUsernameExists):
			c.JSON(409, gin.H{"error": "用户名已存在", "code": "USERNAME_EXISTS"})
		default:
			c.JSON(500, gin.H{"error": "注册失败", "code": "REGISTER_ERROR"})
		}
		return
	}

	c.JSON(200, gin.H{"message": "注册成功"})
}
