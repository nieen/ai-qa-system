package service

import (
	"errors"

	"golang.org/x/crypto/bcrypt"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/ai-qa-system/gateway/internal/middleware"
	"github.com/ai-qa-system/gateway/internal/repository"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

// 错误常量
var (
	ErrUserNotFound    = errors.New("用户不存在")
	ErrWrongPassword   = errors.New("密码错误")
	ErrUserDisabled    = errors.New("账户已被禁用")
	ErrUsernameExists  = errors.New("用户名已存在")
	ErrPrivacyRequired = errors.New("需要同意隐私政策")
	ErrServiceUnavailable = errors.New("服务暂不可用")
)

type authService struct {
	cfg       *config.Config
	userRepo  repository.UserRepository
	auditRepo repository.AuditRepository
	logger    *zap.SugaredLogger
}

// NewAuthService 创建认证服务
func NewAuthService(cfg *config.Config, userRepo repository.UserRepository, auditRepo repository.AuditRepository) AuthService {
	return &authService{
		cfg:       cfg,
		userRepo:  userRepo,
		auditRepo: auditRepo,
		logger:    zap.L().Sugar(),
	}
}

func (s *authService) Login(username, password, clientIP, userAgent string) (*LoginResult, error) {
	user, err := s.userRepo.GetByUsername(username)
	if err != nil {
		s.logger.Errorw("数据库查询用户失败", "username", username, "error", err)
		return nil, ErrServiceUnavailable
	}
	if user == nil {
		_ = s.auditRepo.LogEntry("", "user.login_failed", "session", username,
			clientIP, userAgent, map[string]interface{}{"reason": "user_not_found"})
		return nil, ErrUserNotFound
	}
	if !user.IsActive {
		_ = s.auditRepo.LogEntry("", "user.login_failed", "session", user.ID,
			clientIP, userAgent, map[string]interface{}{"reason": "account_disabled"})
		return nil, ErrUserDisabled
	}

	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(password)); err != nil {
		_ = s.auditRepo.LogEntry("", "user.login_failed", "session", user.ID,
			clientIP, userAgent, map[string]interface{}{"reason": "wrong_password"})
		return nil, ErrWrongPassword
	}

	_ = s.userRepo.UpdateLastLogin(user.ID)

	token, err := middleware.GenerateJWT(user.ID, user.Username, user.Role,
		s.cfg.JWT.Secret, s.cfg.JWT.ExpiryHours)
	if err != nil {
		s.logger.Errorw("JWT 签发失败", "error", err)
		return nil, errors.New("令牌签发失败")
	}

	_ = s.auditRepo.LogEntry(user.ID, "user.login", "session", "",
		clientIP, userAgent, nil)

	return &LoginResult{
		Token: token,
		User: ginUser{
			ID:          user.ID,
			Username:    user.Username,
			Role:        user.Role,
			DisplayName: user.DisplayName,
		},
	}, nil
}

func (s *authService) Register(req RegisterRequest) error {
	if !req.AcceptedPrivacyPolicy {
		return ErrPrivacyRequired
	}

	existing, _ := s.userRepo.GetByUsername(req.Username)
	if existing != nil {
		return ErrUsernameExists
	}

	hashedBytes, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		s.logger.Errorw("密码哈希失败", "error", err)
		return errors.New("注册服务异常")
	}

	userID := uuid.New().String()
	displayName := req.DisplayName
	if displayName == "" {
		displayName = req.Username
	}

	if err := s.userRepo.Create(userID, req.Username, string(hashedBytes), displayName, req.Email); err != nil {
		s.logger.Errorw("创建用户失败", "error", err)
		return errors.New("注册失败")
	}

	_ = s.auditRepo.LogEntry(userID, "user.register", "user", userID,
		req.ClientIP, req.UserAgent, nil)

	s.logger.Infow("用户注册成功",
		"user_id", userID,
		"username", req.Username,
		"ip", req.ClientIP,
	)

	return nil
}

// SetLogger 设置日志记录器（用于 Handler 传入 logger）
func (s *authService) SetLogger(logger *zap.SugaredLogger) {
	s.logger = logger
}
