package proxy

import (
	"sync"
	"time"

	"github.com/ai-qa-system/gateway/internal/middleware"
	"github.com/gomodule/redigo/redis"
)

// ==================== 分布式熔断器（多副本状态共享）====================
//
// 在本地 CircuitBreaker 基础上增加 Redis 状态同步层：
//   - 当本地熔断器状态变化时（OPEN / CLOSED / HALF_OPEN），写入 Redis
//   - 每次 Allow() 检查时，如果 Redis 有更新的状态则拉取
//   - 避免多副本部署下副本 A 已熔断但副本 B 继续发送请求的问题
//
// Redis 存储结构:
//   Key: circuit_breaker:{name}
//   Fields: state (int), failures (int), timestamp (unix_nano)
//   TTL: recovery_timeout × 2（自动清理过期状态）

const cbRedisPrefix = "circuit_breaker:"

// 熔断器状态常量
const (
	cbStateClosed   = 0
	cbStateOpen     = 1
	cbStateHalfOpen = 2
)

// circuitBreakerRedisScript Lua 脚本：原子读取 + 条件写入熔断器状态
var cbSyncScript = redis.NewScript(1, `
local key = KEYS[1]
local local_state = tonumber(ARGV[1])
local local_failures = tonumber(ARGV[2])
local local_ts = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local now = tonumber(ARGV[5])

local redis_state_raw = redis.call("HMGET", key, "state", "failures", "timestamp")
local redis_state = tonumber(redis_state_raw[1])
local redis_failures = tonumber(redis_state_raw[2]) or 0
local redis_ts = tonumber(redis_state_raw[3]) or 0

if redis_state == nil then
    redis.call("HMSET", key,
        "state", local_state,
        "failures", local_failures,
        "timestamp", local_ts
    )
    redis.call("EXPIRE", key, ttl)
    return {local_state, local_failures, local_ts}
end

local time_since_state = now - redis_ts
if redis_state == 1 and time_since_state > ttl * 500000000 then
    redis_state = 2
    redis.call("HMSET", key, "state", 2, "timestamp", now)
    redis.call("EXPIRE", key, ttl)
    return {2, redis_failures, now}
end

if local_ts > redis_ts then
    redis.call("HMSET", key,
        "state", local_state,
        "failures", local_failures,
        "timestamp", local_ts
    )
    redis.call("EXPIRE", key, ttl)
    return {local_state, local_failures, local_ts}
end

return {redis_state, redis_failures, redis_ts}
`)

// SyncCircuitBreaker 同步熔断器状态到 Redis
func SyncCircuitBreaker(name string, localState int, localFailures int, recoveryTimeout time.Duration) (int, int) {
	conn := middleware.GetRedis()
	if conn == nil {
		return localState, localFailures
	}
	defer conn.Close()

	key := cbRedisPrefix + name
	ttl := int(recoveryTimeout.Seconds()) * 2
	if ttl < 60 {
		ttl = 60
	}

	values, err := redis.Ints(cbSyncScript.Do(conn, key,
		localState, localFailures, time.Now().UnixNano(), ttl, time.Now().UnixNano()))
	if err != nil || len(values) < 2 {
		return localState, localFailures
	}

	return values[0], values[1]
}

// DistributedCircuitBreaker 在本地 CircuitBreaker 基础上增加多副本状态同步
type DistributedCircuitBreaker struct {
	local *CircuitBreaker
	name  string
	mu    sync.RWMutex

	remoteState          int
	remoteStateFetchedAt time.Time
	remoteCacheTTL       time.Duration
}

// NewDistributedCircuitBreaker 创建分布式熔断器
func NewDistributedCircuitBreaker(name string, local *CircuitBreaker) *DistributedCircuitBreaker {
	return &DistributedCircuitBreaker{
		local:          local,
		name:           name,
		remoteState:    cbStateClosed,
		remoteCacheTTL: 2 * time.Second,
	}
}

// Allow 检查请求是否允许通过（本地 + 远程双重检查）
func (dcb *DistributedCircuitBreaker) Allow() bool {
	dcb.mu.RLock()
	if dcb.remoteState == cbStateOpen {
		if time.Since(dcb.remoteStateFetchedAt) < dcb.remoteCacheTTL {
			dcb.mu.RUnlock()
			return false
		}
	}
	dcb.mu.RUnlock()

	if !dcb.local.Allow() {
		_, failures := dcb.local.RemoteState()
		redisState, _ := SyncCircuitBreaker(dcb.name, cbStateOpen,
			failures, dcb.local.RemoteRecoveryTimeout())

		dcb.mu.Lock()
		dcb.remoteState = redisState
		dcb.remoteStateFetchedAt = time.Now()
		dcb.mu.Unlock()
		return false
	}

	if time.Since(dcb.remoteStateFetchedAt) > dcb.remoteCacheTTL {
		localState, localFailures := dcb.local.RemoteState()

		redisState, _ := SyncCircuitBreaker(dcb.name, localState,
			localFailures, dcb.local.RemoteRecoveryTimeout())

		dcb.mu.Lock()
		dcb.remoteState = redisState
		dcb.remoteStateFetchedAt = time.Now()
		dcb.mu.Unlock()

		if redisState == cbStateOpen {
			dcb.local.ForceOpen()
			return false
		}
	}

	return true
}

// Success 记录成功
func (dcb *DistributedCircuitBreaker) Success() {
	dcb.local.Success()
	go func() {
		SyncCircuitBreaker(dcb.name, cbStateClosed, 0, dcb.local.RemoteRecoveryTimeout())
	}()
}

// Failure 记录失败
func (dcb *DistributedCircuitBreaker) Failure() {
	dcb.local.Failure()
	if dcb.local.IsOpen() {
		_, failures := dcb.local.RemoteState()
		redisState, _ := SyncCircuitBreaker(dcb.name, cbStateOpen,
			failures, dcb.local.RemoteRecoveryTimeout())
		dcb.mu.Lock()
		dcb.remoteState = redisState
		dcb.remoteStateFetchedAt = time.Now()
		dcb.mu.Unlock()
	}
}

// IsOpen 检查是否熔断
func (dcb *DistributedCircuitBreaker) IsOpen() bool {
	if dcb.local.IsOpen() {
		return true
	}
	dcb.mu.RLock()
	remoteOpen := dcb.remoteState == cbStateOpen
	dcb.mu.RUnlock()
	return remoteOpen
}

// Reset 重置熔断器
func (dcb *DistributedCircuitBreaker) Reset() {
	dcb.local.Reset()
	dcb.mu.Lock()
	dcb.remoteState = cbStateClosed
	dcb.remoteStateFetchedAt = time.Time{}
	dcb.mu.Unlock()
}

// DistributedCircuitBreakerGroup 分布式熔断器组
type DistributedCircuitBreakerGroup struct {
	local *CircuitBreakerGroup
	mu    sync.RWMutex
	dcbs  map[string]*DistributedCircuitBreaker
}

// NewDistributedCircuitBreakerGroup 创建分布式熔断器组
func NewDistributedCircuitBreakerGroup() *DistributedCircuitBreakerGroup {
	return &DistributedCircuitBreakerGroup{
		local: NewCircuitBreakerGroup(),
		dcbs:  make(map[string]*DistributedCircuitBreaker),
	}
}

// GetOrCreate 获取或创建分布式熔断器
func (g *DistributedCircuitBreakerGroup) GetOrCreate(name string, threshold int, timeout time.Duration, halfOpenMax int) *DistributedCircuitBreaker {
	g.mu.RLock()
	dcb, ok := g.dcbs[name]
	g.mu.RUnlock()
	if ok {
		return dcb
	}

	g.mu.Lock()
	defer g.mu.Unlock()
	if dcb, ok := g.dcbs[name]; ok {
		return dcb
	}

	local := g.local.GetOrCreate(name, threshold, timeout, halfOpenMax)
	dcb = NewDistributedCircuitBreaker(name, local)
	g.dcbs[name] = dcb
	return dcb
}
