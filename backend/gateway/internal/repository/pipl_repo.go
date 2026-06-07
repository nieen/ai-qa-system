package repository

import (
	"github.com/ai-qa-system/gateway/internal/database"
)

// PIPLRepository PIPL 数据合规仓储接口
// 直接返回 database 层类型以避免不必要的转换
type PIPLRepository interface {
	RecordConsent(userID, consentType, consentVersion, ipAddress string) error
	ExportUserData(userID string) (*database.UserExportData, error)
	CreateDeletionRequest(userID string) (string, error)
	ConfirmDeletion(requestID, userID string) error
	CancelDeletion(requestID, userID string) error
	CascadeDeleteUserData(userID string) error
	GetPendingDeletionRequests() ([]string, error)
}

type piplRepository struct{}

func NewPIPLRepository() PIPLRepository {
	return &piplRepository{}
}

func (r *piplRepository) RecordConsent(userID, consentType, consentVersion, ipAddress string) error {
	return database.RecordConsent(userID, consentType, consentVersion, ipAddress)
}

func (r *piplRepository) ExportUserData(userID string) (*database.UserExportData, error) {
	return database.ExportUserData(userID)
}

func (r *piplRepository) CreateDeletionRequest(userID string) (string, error) {
	return database.CreateDeletionRequest(userID)
}

func (r *piplRepository) ConfirmDeletion(requestID, userID string) error {
	return database.ConfirmDeletion(requestID, userID)
}

func (r *piplRepository) CancelDeletion(requestID, userID string) error {
	return database.CancelDeletion(requestID, userID)
}

func (r *piplRepository) CascadeDeleteUserData(userID string) error {
	return database.CascadeDeleteUserData(userID)
}

func (r *piplRepository) GetPendingDeletionRequests() ([]string, error) {
	return database.GetPendingDeletionRequests()
}
