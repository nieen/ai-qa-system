package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/gin-gonic/gin"
)

func setupGin() (*gin.Context, *httptest.ResponseRecorder) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest("GET", "/api/v1/user/profile", nil)
	return c, w
}

func TestAuthenticate_MissingToken(t *testing.T) {
	c, w := setupGin()
	handler := Authenticate("test-secret")
	handler(c)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("期望 401，得到 %d", w.Code)
	}
}

func TestAuthenticate_ValidToken(t *testing.T) {
	c, w := setupGin()
	secret := "test-secret"

	token, err := GenerateJWT("user-1", "testuser", "user", secret, 24)
	if err != nil {
		t.Fatalf("JWT 签发失败: %v", err)
	}

	c.Request.Header.Set("Authorization", "Bearer "+token)
	handler := Authenticate(secret)
	handler(c)

	if w.Code != http.StatusOK {
		t.Fatalf("期望 200，得到 %d", w.Code)
	}

	// 验证上下文已注入用户信息
	userID, _ := c.Get(ContextKeyUserID)
	if userID != "user-1" {
		t.Fatalf("期望 user_id=user-1，得到 %v", userID)
	}
	role, _ := c.Get(ContextKeyUserRole)
	if role != "user" {
		t.Fatalf("期望 role=user，得到 %v", role)
	}
}

func TestAuthenticate_InvalidToken(t *testing.T) {
	c, w := setupGin()
	c.Request.Header.Set("Authorization", "Bearer invalid-token-string")

	handler := Authenticate("test-secret")
	handler(c)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("期望 401，得到 %d", w.Code)
	}
}

func TestAuthenticate_WrongSecret(t *testing.T) {
	c, w := setupGin()

	token, _ := GenerateJWT("user-1", "testuser", "user", "secret-a", 24)
	c.Request.Header.Set("Authorization", "Bearer "+token)

	handler := Authenticate("secret-b") // 不同密钥验证
	handler(c)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("期望 401（密钥不匹配），得到 %d", w.Code)
	}
}

func TestAuthenticate_ExpiredToken(t *testing.T) {
	c, w := setupGin()
	secret := "test-secret"

	// 生成已过期的 token（expiry = -1 小时）
	token, err := GenerateJWT("user-1", "testuser", "user", secret, -1)
	if err != nil {
		t.Fatalf("JWT 签发失败: %v", err)
	}

	c.Request.Header.Set("Authorization", "Bearer "+token)
	handler := Authenticate(secret)
	handler(c)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("期望 401（token 已过期），得到 %d", w.Code)
	}
}

func TestAuthenticate_BearerWithoutToken(t *testing.T) {
	c, w := setupGin()
	c.Request.Header.Set("Authorization", "Bearer ")

	handler := Authenticate("test-secret")
	handler(c)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("期望 401，得到 %d", w.Code)
	}
}

func TestAdminRequired_WithAdminRole(t *testing.T) {
	c, w := setupGin()
	c.Set(ContextKeyUserRole, "admin")

	handler := AdminRequired()
	handler(c)

	if w.Code != http.StatusOK {
		t.Fatalf("期望 200（admin 有权限），得到 %d", w.Code)
	}
}

func TestAdminRequired_WithUserRole(t *testing.T) {
	c, w := setupGin()
	c.Set(ContextKeyUserRole, "user")

	handler := AdminRequired()
	handler(c)

	if w.Code != http.StatusForbidden {
		t.Fatalf("期望 403（user 无权限），得到 %d", w.Code)
	}
}

func TestAdminRequired_NoRole(t *testing.T) {
	c, w := setupGin()

	handler := AdminRequired()
	handler(c)

	if w.Code != http.StatusForbidden {
		t.Fatalf("期望 403（未设置 role），得到 %d", w.Code)
	}
}

func TestRateLimiter_Disabled(t *testing.T) {
	cfg := config.RateLimitConfig{Enabled: false}
	handler := RateLimiter(cfg)

	for i := 0; i < 100; i++ {
		rec := httptest.NewRecorder()
		ctx, _ := gin.CreateTestContext(rec)
		ctx.Request = httptest.NewRequest("GET", "/", nil)
		handler(ctx)
		if rec.Code != http.StatusOK {
			t.Fatalf("第 %d 次请求: 限流禁用时应全通过，得到 %d", i+1, rec.Code)
		}
	}
}

func TestLocalRateLimiter_Exceeds(t *testing.T) {
	cfg := config.RateLimitConfig{
		Enabled:           true,
		Type:              "local",
		RequestsPerSecond: 10,
		Burst:             5,
	}
	handler := RateLimiter(cfg)

	for i := 0; i < 10; i++ {
		rec := httptest.NewRecorder()
		ctx, _ := gin.CreateTestContext(rec)
		ctx.Request = httptest.NewRequest("GET", "/", nil)
		handler(ctx)
		if i < 5 && rec.Code != http.StatusOK {
			t.Fatalf("第 %d 次请求 (<=burst): 期望 200，得到 %d", i+1, rec.Code)
		}
	}
}

func TestRequestID(t *testing.T) {
	c, w := setupGin()
	handler := RequestID()
	handler(c)

	if w.Code != http.StatusOK {
		t.Fatalf("期望 200，得到 %d", w.Code)
	}
	requestID, exists := c.Get(ContextKeyRequestID)
	if !exists {
		t.Fatal("期望 RequestID 被注入上下文中")
	}
	if requestID.(string) == "" {
		t.Fatal("期望 RequestID 非空")
	}
}

func TestGenerateAndValidateJWT_RoundTrip(t *testing.T) {
	secret := "my-secret-key"
	token, err := GenerateJWT("u1", "alice", "admin", secret, 24)
	if err != nil {
		t.Fatalf("GenerateJWT 失败: %v", err)
	}

	claims, err := ValidateJWT(token, secret)
	if err != nil {
		t.Fatalf("ValidateJWT 失败: %v", err)
	}

	if claims.UserID != "u1" {
		t.Fatalf("期望 UserID=u1，得到 %s", claims.UserID)
	}
	if claims.Username != "alice" {
		t.Fatalf("期望 Username=alice，得到 %s", claims.Username)
	}
	if claims.Role != "admin" {
		t.Fatalf("期望 Role=admin，得到 %s", claims.Role)
	}
}

func TestValidateJWT_Expired(t *testing.T) {
	secret := "test-secret"
	// 过期 token
	token, err := GenerateJWT("u1", "alice", "user", secret, -24)
	if err != nil {
		t.Fatalf("GenerateJWT 失败: %v", err)
	}

	_, err = ValidateJWT(token, secret)
	if err == nil {
		t.Fatal("期望 ValidateJWT 返回错误（已过期），得到 nil")
	}
}

func TestValidateJWT_Malformed(t *testing.T) {
	_, err := ValidateJWT("not-a-jwt-token", "secret")
	if err == nil {
		t.Fatal("期望 ValidateJWT 返回错误（格式错误），得到 nil")
	}
}

func TestValidateJWT_WrongKey(t *testing.T) {
	secret := "real-secret"
	wrongSecret := "wrong-secret"

	token, err := GenerateJWT("u1", "alice", "user", secret, 24)
	if err != nil {
		t.Fatalf("GenerateJWT 失败: %v", err)
	}

	_, err = ValidateJWT(token, wrongSecret)
	if err == nil {
		t.Fatal("期望 ValidateJWT 返回错误（密钥不匹配），得到 nil")
	}
}
