package service

import (
	"errors"
	"testing"
	"time"

	"golang.org/x/crypto/bcrypt"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/ai-qa-system/gateway/internal/repository"
)

// ---- Mock repositories ----

type mockUserRepo struct {
	users    map[string]*repository.User // key: username
	getErr   error
	createFn func(id, username, passwordHash, displayName, email string) error
}

func newMockUserRepo() *mockUserRepo {
	return &mockUserRepo{
		users: make(map[string]*repository.User),
	}
}

func (m *mockUserRepo) GetByUsername(username string) (*repository.User, error) {
	if m.getErr != nil {
		return nil, m.getErr
	}
	u, ok := m.users[username]
	if !ok {
		return nil, nil
	}
	return u, nil
}

func (m *mockUserRepo) GetByID(userID string) (*repository.User, error) {
	for _, u := range m.users {
		if u.ID == userID {
			return u, nil
		}
	}
	return nil, nil
}

func (m *mockUserRepo) Create(id, username, passwordHash, displayName, email string) error {
	if m.createFn != nil {
		return m.createFn(id, username, passwordHash, displayName, email)
	}
	m.users[username] = &repository.User{
		ID:           id,
		Username:     username,
		PasswordHash: passwordHash,
		DisplayName:  displayName,
		Email:        email,
		Role:         "user",
		IsActive:     true,
		CreatedAt:    time.Now(),
	}
	return nil
}

func (m *mockUserRepo) UpdateLastLogin(userID string) error {
	return nil
}

func (m *mockUserRepo) ListUsers() ([]repository.User, error) {
	var list []repository.User
	for _, u := range m.users {
		list = append(list, *u)
	}
	return list, nil
}

type mockAuditRepo struct {
	entries []string
}

func newMockAuditRepo() *mockAuditRepo {
	return &mockAuditRepo{}
}

func (m *mockAuditRepo) LogEntry(userID, action, resourceType, resourceID, ipAddress, userAgent string, details map[string]interface{}) error {
	m.entries = append(m.entries, action)
	return nil
}

func (m *mockAuditRepo) QueryLogs(limit, offset int) ([]repository.AuditLog, int, error) {
	return nil, 0, nil
}

func (m *mockAuditRepo) CleanupOldLogs(retentionDays int) (int64, error) {
	return 0, nil
}

// ---- Tests ----

func newTestConfig() *config.Config {
	return &config.Config{
		JWT: config.JWTConfig{
			Secret:      "test-secret-key-for-testing-only",
			ExpiryHours: 24,
		},
	}
}

func TestLogin_Success(t *testing.T) {
	userRepo := newMockUserRepo()
	auditRepo := newMockAuditRepo()
	cfg := newTestConfig()

	// 预创建用户（密码: "correct-password"）
	hash, _ := bcrypt.GenerateFromPassword([]byte("correct-password"), bcrypt.DefaultCost)
	userRepo.users["testuser"] = &repository.User{
		ID:           "u1",
		Username:     "testuser",
		PasswordHash: string(hash),
		DisplayName:  "测试用户",
		Role:         "user",
		IsActive:     true,
	}

	svc := NewAuthService(cfg, userRepo, auditRepo)
	result, err := svc.Login("testuser", "correct-password", "127.0.0.1", "test-agent")

	if err != nil {
		t.Fatalf("期望登录成功，得到错误: %v", err)
	}
	if result.Token == "" {
		t.Fatal("期望返回 JWT token，得到空字符串")
	}
	if result.User.Username != "testuser" {
		t.Fatalf("期望 username=testuser，得到 %s", result.User.Username)
	}

	// 验证审计日志: login_failed(not_found) 不应存在, login 应存在
	foundLogin := false
	for _, e := range auditRepo.entries {
		if e == "user.login" {
			foundLogin = true
		}
	}
	if !foundLogin {
		t.Fatal("期望审计日志包含 user.login")
	}
}

func TestLogin_UserNotFound(t *testing.T) {
	userRepo := newMockUserRepo()
	auditRepo := newMockAuditRepo()
	cfg := newTestConfig()

	svc := NewAuthService(cfg, userRepo, auditRepo)
	_, err := svc.Login("nonexistent", "any-password", "127.0.0.1", "test-agent")

	if !errors.Is(err, ErrUserNotFound) {
		t.Fatalf("期望 ErrUserNotFound，得到 %v", err)
	}
}

func TestLogin_UserDisabled(t *testing.T) {
	userRepo := newMockUserRepo()
	auditRepo := newMockAuditRepo()
	cfg := newTestConfig()

	userRepo.users["disabled"] = &repository.User{
		ID:           "u2",
		Username:     "disabled",
		PasswordHash: "hash",
		DisplayName:  "已禁用用户",
		IsActive:     false,
	}

	svc := NewAuthService(cfg, userRepo, auditRepo)
	_, err := svc.Login("disabled", "any-password", "127.0.0.1", "test-agent")

	if !errors.Is(err, ErrUserDisabled) {
		t.Fatalf("期望 ErrUserDisabled，得到 %v", err)
	}
}

func TestLogin_WrongPassword(t *testing.T) {
	userRepo := newMockUserRepo()
	auditRepo := newMockAuditRepo()
	cfg := newTestConfig()

	hash, _ := bcrypt.GenerateFromPassword([]byte("real-password"), bcrypt.DefaultCost)
	userRepo.users["validuser"] = &repository.User{
		ID:           "u3",
		Username:     "validuser",
		PasswordHash: string(hash),
		IsActive:     true,
	}

	svc := NewAuthService(cfg, userRepo, auditRepo)
	_, err := svc.Login("validuser", "wrong-password", "127.0.0.1", "test-agent")

	if !errors.Is(err, ErrWrongPassword) {
		t.Fatalf("期望 ErrWrongPassword，得到 %v", err)
	}
}

func TestLogin_DatabaseError(t *testing.T) {
	userRepo := newMockUserRepo()
	auditRepo := newMockAuditRepo()
	cfg := newTestConfig()

	userRepo.getErr = errors.New("connection refused")

	svc := NewAuthService(cfg, userRepo, auditRepo)
	_, err := svc.Login("anyuser", "any", "127.0.0.1", "test-agent")

	if !errors.Is(err, ErrServiceUnavailable) {
		t.Fatalf("期望 ErrServiceUnavailable，得到 %v", err)
	}
}

func TestRegister_Success(t *testing.T) {
	userRepo := newMockUserRepo()
	auditRepo := newMockAuditRepo()
	cfg := newTestConfig()

	svc := NewAuthService(cfg, userRepo, auditRepo)
	err := svc.Register(RegisterRequest{
		Username:              "newuser",
		Password:              "pass123456",
		DisplayName:           "新用户",
		Email:                 "new@test.com",
		ClientIP:              "127.0.0.1",
		UserAgent:             "test",
		AcceptedPrivacyPolicy: true,
	})

	if err != nil {
		t.Fatalf("期望注册成功，得到错误: %v", err)
	}

	// 验证用户已创建
	user, _ := userRepo.GetByUsername("newuser")
	if user == nil {
		t.Fatal("期望用户被创建，但未找到")
	}
	if user.DisplayName != "新用户" {
		t.Fatalf("期望 DisplayName=新用户，得到 %s", user.DisplayName)
	}
}

func TestRegister_PrivacyNotAccepted(t *testing.T) {
	userRepo := newMockUserRepo()
	auditRepo := newMockAuditRepo()
	cfg := newTestConfig()

	svc := NewAuthService(cfg, userRepo, auditRepo)
	err := svc.Register(RegisterRequest{
		Username:              "newuser",
		Password:              "pass123456",
		AcceptedPrivacyPolicy: false,
	})

	if !errors.Is(err, ErrPrivacyRequired) {
		t.Fatalf("期望 ErrPrivacyRequired，得到 %v", err)
	}
}

func TestRegister_UsernameExists(t *testing.T) {
	userRepo := newMockUserRepo()
	auditRepo := newMockAuditRepo()
	cfg := newTestConfig()

	userRepo.users["existing"] = &repository.User{
		ID:       "u1",
		Username: "existing",
	}

	svc := NewAuthService(cfg, userRepo, auditRepo)
	err := svc.Register(RegisterRequest{
		Username:              "existing",
		Password:              "pass123456",
		AcceptedPrivacyPolicy: true,
	})

	if !errors.Is(err, ErrUsernameExists) {
		t.Fatalf("期望 ErrUsernameExists，得到 %v", err)
	}
}
