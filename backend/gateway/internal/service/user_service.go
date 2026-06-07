package service

import (
	"github.com/ai-qa-system/gateway/internal/repository"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

type userService struct {
	userRepo  repository.UserRepository
	auditRepo repository.AuditRepository
	piplRepo  repository.PIPLRepository
	logger    *zap.SugaredLogger
}

func NewUserService(
	userRepo repository.UserRepository,
	auditRepo repository.AuditRepository,
	piplRepo repository.PIPLRepository,
) UserService {
	return &userService{
		userRepo:  userRepo,
		auditRepo: auditRepo,
		piplRepo:  piplRepo,
		logger:    zap.L().Sugar(),
	}
}

func (s *userService) GetProfile(userID string) (*UserProfile, error) {
	user, err := s.userRepo.GetByID(userID)
	if err != nil {
		s.logger.Errorw("查询用户失败", "user_id", userID, "error", err)
		return nil, ErrServiceUnavailable
	}
	if user == nil {
		return nil, ErrUserNotFound
	}

	return &UserProfile{
		ID:          user.ID,
		Username:    user.Username,
		DisplayName: user.DisplayName,
		Email:       user.Email,
		Role:        user.Role,
		IsActive:    user.IsActive,
	}, nil
}

func (s *userService) ExportData(userID string) (interface{}, error) {
	data, err := s.piplRepo.ExportUserData(userID)
	if err != nil {
		s.logger.Errorw("导出用户数据失败", "user_id", userID, "error", err)
		return nil, ErrServiceUnavailable
	}
	if data == nil {
		return nil, ErrUserNotFound
	}

	_ = s.auditRepo.LogEntry(userID, "user.export_data", "user", userID,
		"", "", nil)

	return data, nil
}

func (s *userService) Logout(userID, tokenID string) error {
	// 预留：Token 黑名单
	_ = s.auditRepo.LogEntry(userID, "user.logout", "session", tokenID,
		"", "", nil)
	return nil
}

func (s *userService) RequestDeletion(userID string) (string, error) {
	requestID, err := s.piplRepo.CreateDeletionRequest(userID)
	if err != nil {
		s.logger.Errorw("创建删除请求失败", "user_id", userID, "error", err)
		return "", ErrServiceUnavailable
	}

	_ = s.auditRepo.LogEntry(userID, "user.delete_request", "user", userID,
		"", "", map[string]interface{}{"request_id": requestID})

	return requestID, nil
}

func (s *userService) ConfirmDeletion(requestID, userID string) error {
	if err := s.piplRepo.ConfirmDeletion(requestID, userID); err != nil {
		s.logger.Errorw("确认删除失败", "request_id", requestID, "error", err)
		return err
	}

	// 级联删除用户所有数据
	if err := s.piplRepo.CascadeDeleteUserData(userID); err != nil {
		s.logger.Errorw("级联删除用户数据失败", "user_id", userID, "error", err)
		return ErrServiceUnavailable
	}

	_ = s.auditRepo.LogEntry(userID, "user.delete_confirmed", "user", userID,
		"", "", nil)

	return nil
}

func (s *userService) CancelDeletion(requestID, userID string) error {
	if err := s.piplRepo.CancelDeletion(requestID, userID); err != nil {
		s.logger.Errorw("取消删除失败", "request_id", requestID, "error", err)
		return err
	}

	_ = s.auditRepo.LogEntry(userID, "user.delete_cancelled", "user", userID,
		"", "", nil)

	return nil
}

func (s *userService) SetLogger(logger *zap.SugaredLogger) {
	s.logger = logger
}

// getRegisterID 生成注册时的用户 ID（外部使用）
func NewRegisterID() string {
	return uuid.New().String()
}
