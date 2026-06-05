package middleware

import (
	"testing"
	"time"

	"github.com/ai-qa-system/gateway/internal/config"
)

func TestGenerateAndValidateJWT(t *testing.T) {
	secret := "test-secret-12345"
	userID := "user-1"
	username := "testuser"
	role := "admin"
	expiryHours := 24

	token, err := GenerateJWT(userID, username, role, secret, expiryHours)
	if err != nil {
		t.Fatalf("GenerateJWT() error = %v", err)
	}

	if token == "" {
		t.Fatal("GenerateJWT() 返回空令牌")
	}

	claims, err := ValidateJWT(token, secret)
	if err != nil {
		t.Fatalf("ValidateJWT() error = %v", err)
	}

	if claims.UserID != userID {
		t.Errorf("UserID = %q, 期望 %q", claims.UserID, userID)
	}
	if claims.Username != username {
		t.Errorf("Username = %q, 期望 %q", claims.Username, username)
	}
	if claims.Role != role {
		t.Errorf("Role = %q, 期望 %q", claims.Role, role)
	}
}

func TestValidateJWTInvalidSecret(t *testing.T) {
	secret := "correct-secret"
	token, _ := GenerateJWT("u1", "user", "user", secret, 24)

	_, err := ValidateJWT(token, "wrong-secret")
	if err == nil {
		t.Error("使用错误密钥验证应失败")
	}
}

func TestValidateJWTExpired(t *testing.T) {
	secret := "test-secret"
	// 生成已过期的令牌 (expiry = -1)
	token, err := GenerateJWT("u1", "user", "user", secret, -1)
	if err != nil {
		t.Fatalf("GenerateJWT() error = %v", err)
	}

	_, err = ValidateJWT(token, secret)
	if err == nil {
		t.Error("过期令牌验证应失败")
	}
}

func TestValidateJWTMalformed(t *testing.T) {
	_, err := ValidateJWT("not-a-valid-token", "secret")
	if err == nil {
		t.Error("畸形令牌验证应失败")
	}
}

func TestGenerateJWTClaims(t *testing.T) {
	secret := "test-secret"
	token, _ := GenerateJWT("u1", "tester", "admin", secret, 48)

	claims, _ := ValidateJWT(token, secret)

	if claims.Issuer != "ai-qa-system" {
		t.Errorf("Issuer = %q, 期望 ai-qa-system", claims.Issuer)
	}

	// 检查过期时间
	expiry := claims.ExpiresAt.Time
	expectedExpiry := time.Now().Add(48 * time.Hour)
	if expiry.Before(time.Now()) {
		t.Error("令牌已过期")
	}
	if expiry.After(expectedExpiry.Add(time.Minute)) {
		t.Error("过期时间超出预期范围")
	}
}

func TestRateLimiterLocal(t *testing.T) {
	// 验证本地限流器创建 (不报错)
	cfg := config.RateLimitConfig{
		Enabled:           true,
		Type:              "local",
		RequestsPerSecond: 100,
		Burst:             200,
	}

	handler := RateLimiter(cfg)
	if handler == nil {
		t.Error("RateLimiter() 返回 nil")
	}
}

func TestRateLimiterDisabled(t *testing.T) {
	cfg := config.RateLimitConfig{Enabled: false}
	handler := RateLimiter(cfg)
	if handler == nil {
		t.Error("禁用的限流器不应返回 nil")
	}
}
