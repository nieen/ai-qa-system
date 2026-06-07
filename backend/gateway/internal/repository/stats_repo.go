package repository

import (
	"github.com/ai-qa-system/gateway/internal/database"
)

// SystemStats 系统统计
type SystemStats struct {
	TotalKBs       int
	TotalDocuments int
	TotalChunks    int64
	TotalUsers     int
}

// StatsRepository 系统统计仓储接口
type StatsRepository interface {
	GetSystemStats() (*SystemStats, error)
	CleanupOldConversations(retentionDays int) (int64, error)
}

type statsRepository struct{}

func NewStatsRepository() StatsRepository {
	return &statsRepository{}
}

func (r *statsRepository) GetSystemStats() (*SystemStats, error) {
	stats, err := database.GetSystemStats()
	if err != nil {
		return nil, err
	}
	return &SystemStats{
		TotalKBs:       stats.TotalKBs,
		TotalDocuments: stats.TotalDocuments,
		TotalChunks:    stats.TotalChunks,
		TotalUsers:     stats.TotalUsers,
	}, nil
}

func (r *statsRepository) CleanupOldConversations(retentionDays int) (int64, error) {
	return database.CleanupOldConversations(retentionDays)
}
