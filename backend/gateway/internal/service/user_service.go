package service

import (
	"net/http"

	"github.com/ai-qa-system/gateway/internal/repository"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

type userService struct {
	userRepo        repository.UserRepository
	auditRepo       repository.AuditRepository
	piplRepo        repository.PIPLRepository
	ragAPIBaseURL   string
	ragHTTPClient   *http.Client
	logger          *zap.SugaredLogger
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

func (s *userService) SetRAGAPI(baseURL string, client *http.Client) {
	s.ragAPIBaseURL = baseURL
	s.ragHTTPClient = client
}

func (s *userService) deleteRAGUserData(userID string) {
	if s.ragAPIBaseURL == "" || s.ragHTTPClient == nil {
		s.logger.Warnw("RAG API 未配置，跳过 RAG 数据清理", "user_id", userID)
		return
	}
	deleteURL := s.ragAPIBaseURL + "/admin/users/" + userID + "/data"
	req, err := http.NewRequest("DELETE", deleteURL, nil)
	if err != nil {
		s.logger.Warnw("RAG 用户数据删除请求创建失败", "user_id", userID, "error", err)
		return
	}
	resp, err := s.ragHTTPClient.Do(req)
	if err != nil {
		s.logger.Warnw("RAG 用户数据删除失败", "user_id", userID, "error", err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode == 200 {
		s.logger.Infow("RAG 用户数据已通过 API 删除", "user_id", userID)
	} else {
		s.logger.Warnw("RAG 用户数据删除返回非 200", "user_id", userID, "status", resp.StatusCode)
	}
}

func (s *userService) ConfirmDeletion(requestID, userID string) error {
	// Step 1: 通过 RAG API 清理 RAG 所属数据 (对话/消息/文档关联)
	s.deleteRAGUserData(userID)

	// Step 2: 确认删除请求
	if err := s.piplRepo.ConfirmDeletion(requestID, userID); err != nil {
		s.logger.Errorw("确认删除失败", "request_id", requestID, "error", err)
		return err
	}

	// Step 3: 级联删除网关本地数据 (审计日志/同意记录/用户)
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
