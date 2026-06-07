package service

import "net/http"

// LoginResult 登录结果
type LoginResult struct {
	Token string
	User  ginUser
}

type ginUser struct {
	ID          string `json:"id"`
	Username    string `json:"username"`
	Role        string `json:"role"`
	DisplayName string `json:"display_name"`
}

// RegisterRequest 注册请求参数
type RegisterRequest struct {
	Username              string
	Password              string
	DisplayName           string
	Email                 string
	ClientIP              string
	UserAgent             string
	AcceptedPrivacyPolicy bool
}

// AuthService 认证服务接口
type AuthService interface {
	Login(username, password, clientIP, userAgent string) (*LoginResult, error)
	Register(req RegisterRequest) error
}

// UserProfile 用户资料
type UserProfile struct {
	ID          string `json:"id"`
	Username    string `json:"username"`
	DisplayName string `json:"display_name"`
	Email       string `json:"email"`
	Role        string `json:"role"`
	IsActive    bool   `json:"is_active"`
}

// UserService 用户服务接口
type UserService interface {
	GetProfile(userID string) (*UserProfile, error)
	ExportData(userID string) (interface{}, error)
	Logout(userID, tokenID string) error
	RequestDeletion(userID string) (string, error)
	ConfirmDeletion(requestID, userID string) error
	CancelDeletion(requestID, userID string) error
	// SetRAGAPI 设置 RAG API 基础 URL（用于级联删除 RAG 所属数据）
	SetRAGAPI(baseURL string, client *http.Client)
}

// AuditLogDTO 审计日志 DTO
type AuditLogDTO struct {
	ID           string `json:"id"`
	UserID       string `json:"user_id"`
	Action       string `json:"action"`
	ResourceType string `json:"resource_type"`
	ResourceID   string `json:"resource_id"`
	IPAddress    string `json:"ip_address"`
	UserAgent    string `json:"user_agent"`
	CreatedAt    string `json:"created_at"`
}

// CleanupResult 清理结果
type CleanupResult struct {
	ConversationsDeleted int64 `json:"conversations_deleted"`
	AuditLogsDeleted     int64 `json:"audit_logs_deleted"`
}

// AdminService 管理服务接口
type AdminService interface {
	GetUserCount() (int, error)
	ListUsers(adminID string) (interface{}, error)
	UpdateUserRole(adminID, userID, role, clientIP, userAgent string) error
	GetAuditLogs(limit, offset int) ([]AuditLogDTO, int, error)
	Cleanup(adminID, clientIP, userAgent string, convDays, logDays int) (*CleanupResult, error)
}
