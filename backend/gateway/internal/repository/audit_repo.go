package repository

import (
	"time"

	"github.com/ai-qa-system/gateway/internal/database"
)

// AuditLog 审计日志行
type AuditLog struct {
	ID           string
	UserID       string
	Action       string
	ResourceType string
	ResourceID   string
	IPAddress    string
	UserAgent    string
	CreatedAt    string
}

// AuditRepository 审计日志仓储接口
type AuditRepository interface {
	LogEntry(userID, action, resourceType, resourceID, ipAddress, userAgent string, details map[string]interface{}) error
	QueryLogs(limit, offset int) ([]AuditLog, int, error)
	CleanupOldLogs(retentionDays int) (int64, error)
}

type auditRepository struct{}

func NewAuditRepository() AuditRepository {
	return &auditRepository{}
}

func (r *auditRepository) LogEntry(userID, action, resourceType, resourceID, ipAddress, userAgent string, details map[string]interface{}) error {
	return database.AuditLogEntry(userID, action, resourceType, resourceID, ipAddress, userAgent, details)
}

func (r *auditRepository) QueryLogs(limit, offset int) ([]AuditLog, int, error) {
	rows, total, err := database.QueryAuditLogs(limit, offset)
	if err != nil {
		return nil, 0, err
	}
	logs := make([]AuditLog, len(rows))
	for i, row := range rows {
		logs[i] = AuditLog{
			ID:           row.ID,
			UserID:       row.UserID,
			Action:       row.Action,
			ResourceType: row.ResourceType,
			ResourceID:   row.ResourceID,
			IPAddress:    row.IPAddress,
			UserAgent:    row.UserAgent,
			CreatedAt:    row.CreatedAt.Format(time.RFC3339),
		}
	}
	return logs, total, nil
}

func (r *auditRepository) CleanupOldLogs(retentionDays int) (int64, error) {
	return database.CleanupOldAuditLogs(retentionDays)
}
