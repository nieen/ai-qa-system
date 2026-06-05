package middleware

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/gomodule/redigo/redis"
)

// ==================== Token 黑名单（多副本安全）====================
//
// 使用 Redis 集中存储，解决多副本部署下的 Token 吊销不一致问题。
// 每个被吊销的 Token 存储为: key = "blacklist:{hash}"，TTL = JWT 剩余有效期。
// 副本 A 登出一个 Token 后，副本 B 也能读到黑名单状态。

const (
	blacklistKeyPrefix = "blacklist:"
)

// RevokeToken 将令牌加入 Redis 黑名单
// 存储时长 = JWT 剩余有效期（最多 24 小时）
func RevokeToken(token string, expiresAt time.Time) {
	conn := GetRedis()
	if conn == nil {
		return // Redis 不可用，接受降级（登出在当前副本生效）
	}
	defer conn.Close()

	key := blacklistKey(token)
	ttl := time.Until(expiresAt)
	if ttl <= 0 || ttl > 24*time.Hour {
		ttl = 24 * time.Hour
	}

	_, err := conn.Do("SET", key, "1", "EX", int(ttl.Seconds()))
	if err != nil {
		// 降级：只记录日志，不影响主流程
		logger.Warn(fmt.Sprintf("Token 黑名单写入失败: %v", err))
	}
}

// isTokenRevoked 检查 Token 是否已被吊销
func isTokenRevoked(token string) bool {
	conn := GetRedis()
	if conn == nil {
		return false // Redis 不可用，降级为全部放行
	}
	defer conn.Close()

	key := blacklistKey(token)
	exists, err := redis.Bool(conn.Do("EXISTS", key))
	if err != nil {
		return false
	}
	return exists
}

// blacklistKey 对 Token 取 SHA256 摘要的前 16 位作为 Redis Key
// 避免在 Redis key 中暴露完整 JWT
func blacklistKey(token string) string {
	h := sha256.Sum256([]byte(token))
	return blacklistKeyPrefix + hex.EncodeToString(h[:8])
}
