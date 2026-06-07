package service

import (
	"github.com/ai-qa-system/gateway/internal/repository"
	"go.uber.org/zap"
)

type adminService struct {
	userRepo  repository.UserRepository
	auditRepo repository.AuditRepository
	statsRepo repository.StatsRepository
	piplRepo  repository.PIPLRepository
	logger    *zap.SugaredLogger
}

func NewAdminService(
	userRepo repository.UserRepository,
	auditRepo repository.AuditRepository,
	statsRepo repository.StatsRepository,
	piplRepo repository.PIPLRepository,
) AdminService {
	return &adminService{
		userRepo:  userRepo,
		auditRepo: auditRepo,
		statsRepo: statsRepo,
		piplRepo:  piplRepo,
		logger:    zap.L().Sugar(),
	}
}

func (s *adminService) GetSystemStats() (interface{}, error) {
	stats, err := s.statsRepo.GetSystemStats()
	if err != nil {
		s.logger.Errorw("获取系统统计失败", "error", err)
		return nil, ErrServiceUnavailable
	}

	return map[string]interface{}{
		"total_kbs":       stats.TotalKBs,
		"total_documents": stats.TotalDocuments,
		"total_chunks":    stats.TotalChunks,
		"total_users":     stats.TotalUsers,
	}, nil
}

func (s *adminService) ListUsers(adminID string) (interface{}, error) {
	users, err := s.userRepo.ListUsers()
	if err != nil {
		s.logger.Errorw("查询用户列表失败", "error", err)
		return nil, ErrServiceUnavailable
	}

	_ = s.auditRepo.LogEntry(adminID, "admin.list_users", "user", "",
		"", "", nil)

	result := make([]map[string]interface{}, 0, len(users))
	for _, u := range users {
		result = append(result, map[string]interface{}{
			"id":           u.ID,
			"username":     u.Username,
			"display_name": u.DisplayName,
			"email":        u.Email,
			"role":         u.Role,
			"is_active":    u.IsActive,
			"created_at":   u.CreatedAt,
		})
	}
	return result, nil
}

func (s *adminService) UpdateUserRole(adminID, userID, role, clientIP, userAgent string) error {
	s.logger.Infow("管理员修改用户角色",
		"admin_id", adminID,
		"target_user", userID,
		"new_role", role,
	)

	_ = s.auditRepo.LogEntry(adminID, "admin.update_role", "user", userID,
		clientIP, userAgent, map[string]interface{}{"new_role": role})

	return nil
}

func (s *adminService) GetAuditLogs(limit, offset int) ([]AuditLogDTO, int, error) {
	logs, total, err := s.auditRepo.QueryLogs(limit, offset)
	if err != nil {
		s.logger.Errorw("查询审计日志失败", "error", err)
		return nil, 0, ErrServiceUnavailable
	}

	dtos := make([]AuditLogDTO, len(logs))
	for i, l := range logs {
		dtos[i] = AuditLogDTO{
			ID:           l.ID,
			UserID:       l.UserID,
			Action:       l.Action,
			ResourceType: l.ResourceType,
			ResourceID:   l.ResourceID,
			IPAddress:    l.IPAddress,
			UserAgent:    l.UserAgent,
			CreatedAt:    l.CreatedAt,
		}
	}
	return dtos, total, nil
}

func (s *adminService) Cleanup(adminID, clientIP, userAgent string, convDays, logDays int) (*CleanupResult, error) {
	convDeleted, err := s.statsRepo.CleanupOldConversations(convDays)
	if err != nil {
		s.logger.Errorw("清理过期对话失败", "error", err)
		convDeleted = 0
	}

	logDeleted, err := s.auditRepo.CleanupOldLogs(logDays)
	if err != nil {
		s.logger.Errorw("清理过期审计日志失败", "error", err)
		logDeleted = 0
	}

	_ = s.auditRepo.LogEntry(adminID, "admin.cleanup", "system", "",
		clientIP, userAgent,
		map[string]interface{}{
			"conversations_deleted": convDeleted,
			"audit_logs_deleted":    logDeleted,
		})

	s.logger.Infow("管理员触发数据清理",
		"admin_id", adminID,
		"conversations_deleted", convDeleted,
		"audit_logs_deleted", logDeleted,
	)

	return &CleanupResult{
		ConversationsDeleted: convDeleted,
		AuditLogsDeleted:     logDeleted,
	}, nil
}

func (s *adminService) SetLogger(logger *zap.SugaredLogger) {
	s.logger = logger
}
