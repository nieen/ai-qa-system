package handler

// ==================== 请求 DTO ====================

// LoginRequest 登录请求
type LoginRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

// RegisterRequest 注册请求
type RegisterRequest struct {
	Username              string `json:"username" binding:"required"`
	Password              string `json:"password" binding:"required,min=6"`
	DisplayName           string `json:"display_name"`
	Email                 string `json:"email"`
	AcceptedPrivacyPolicy bool   `json:"accepted_privacy_policy"`
}

// UpdateUserRoleRequest 更新角色请求
type UpdateUserRoleRequest struct {
	Role string `json:"role" binding:"required"`
}
