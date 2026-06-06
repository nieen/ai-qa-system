package handler

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

// 熔断器状态常量（与 circuit_breaker.go 一致）
const (
	cbStateClosed   = 0
	cbStateOpen     = 1
	cbStateHalfOpen = 2
)

// circuitBreakerRedisScript Lua 脚本：原子读取 + 条件写入熔断器状态
// KEYS[1] = circuit_breaker:{name}
// ARGV[1] = 当前副本的本地状态 (int)
// ARGV[2] = 当前副本的失败计数 (int)
// ARGV[3] = 当前副本的时间戳 (unix nano)
// ARGV[4] = TTL (seconds)
// ARGV[5] = 当前时间戳 (unix nano, 由应用层传入，避免 Lua 内调用阻塞的 TIME 命令)
//
// 返回值:
//
//	[state, failures, timestamp]  — 当前 Redis 中的最新状态
//
// 规则:
//  1. 如果 Redis 中没有该 key → 写入当前副本状态，返回当前副本状态
//  2. 如果 Redis 中状态是 OPEN 且已超时 → 自动切换到 HALF_OPEN
//  3. 如果当前副本状态比 Redis 状态更新 → 更新 Redis
//  4. 否则返回 Redis 中的状态（说明其他副本已更新）
var cbSyncScript = redis.NewScript(1, `
local key = KEYS[1]
local local_state = tonumber(ARGV[1])
local local_failures = tonumber(ARGV[2])
local local_ts = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local now = tonumber(ARGV[5])

-- 读取 Redis 当前状态
local redis_state_raw = redis.call("HMGET", key, "state", "failures", "timestamp")
local redis_state = tonumber(redis_state_raw[1])
local redis_failures = tonumber(redis_state_raw[2]) or 0
local redis_ts = tonumber(redis_state_raw[3]) or 0

if redis_state == nil then
    -- Key 不存在 → 写入当前副本状态
    redis.call("HMSET", key,
        "state", local_state,
        "failures", local_failures,
        "timestamp", local_ts
    )
    redis.call("EXPIRE", key, ttl)
    return {local_state, local_failures, local_ts}
end

-- 检查 OPEN 状态是否超时（timestamp + recovery_timeout < now）
local time_since_state = now - redis_ts
if redis_state == 1 and time_since_state > ttl * 500000000 then
    -- OPEN 已超时 → 推进到 HALF_OPEN
    redis_state = 2
    redis.call("HMSET", key, "state", 2, "timestamp", now)
    redis.call("EXPIRE", key, ttl)
    return {2, redis_failures, now}
end

-- 如果本地副本状态更新（timestamp 更大）→ 更新 Redis
if local_ts > redis_ts then
    redis.call("HMSET", key,
        "state", local_state,
        "failures", local_failures,
        "timestamp", local_ts
    )
    redis.call("EXPIRE", key, ttl)
    return {local_state, local_failures, local_ts}
end

-- 返回 Redis 最新状态
return {redis_state, redis_failures, redis_ts}
`)

// SyncCircuitBreaker 同步熔断器状态到 Redis（由 Allow/Success/Failure 调用）
// 返回 Redis 中的最新状态，调用方应根据此状态调整本地熔断器
//
// 如果 Redis 不可用，返回 (localState, localFailures)，即信任本地状态
func SyncCircuitBreaker(name string, localState int, localFailures int, recoveryTimeout time.Duration) (int, int) {
	conn := middleware.GetRedis()
	if conn == nil {
		return localState, localFailures // 降级到本地
	}
	defer conn.Close()

	key := cbRedisPrefix + name
	ttl := int(recoveryTimeout.Seconds()) * 2
	if ttl < 60 {
		ttl = 60 // 最小 TTL 60 秒
	}

	values, err := redis.Ints(cbSyncScript.Do(conn, key,
		localState, localFailures, time.Now().UnixNano(), ttl, time.Now().UnixNano()))
	if err != nil || len(values) < 2 {
		return localState, localFailures
	}

	return values[0], values[1]
}

// ==================== DistributedCircuitBreaker ====================

// DistributedCircuitBreaker 在本地 CircuitBreaker 基础上增加多副本状态同步
type DistributedCircuitBreaker struct {
	local *CircuitBreaker
	name  string
	mu    sync.RWMutex

	// 最近从 Redis 读取的状态（用于快速拒绝，避免每次请求都查 Redis）
	remoteState          int
	remoteStateFetchedAt time.Time
	remoteCacheTTL       time.Duration // 远程状态缓存寿命
}

// NewDistributedCircuitBreaker 创建分布式熔断器
func NewDistributedCircuitBreaker(name string, local *CircuitBreaker) *DistributedCircuitBreaker {
	return &DistributedCircuitBreaker{
		local:          local,
		name:           name,
		remoteState:    cbStateClosed,
		remoteCacheTTL: 2 * time.Second, // 每 2 秒刷新一次远程状态
	}
}

// Allow 检查请求是否允许通过（本地 + 远程双重检查）
func (dcb *DistributedCircuitBreaker) Allow() bool {
	// Step 1: 检查远程缓存状态（快速拒绝）
	dcb.mu.RLock()
	if dcb.remoteState == cbStateOpen {
		// 远程缓存显示已熔断 → 检查缓存是否过期
		if time.Since(dcb.remoteStateFetchedAt) < dcb.remoteCacheTTL {
			dcb.mu.RUnlock()
			return false // 确信其他副本已熔断此服务
		}
	}
	dcb.mu.RUnlock()

	// Step 2: 本地熔断器检查（快速路径）
	if !dcb.local.Allow() {
		// 本地已熔断 → 获取状态同步到 Redis（通知其他副本）
		_, failures := dcb.local.RemoteState()
		redisState, _ := SyncCircuitBreaker(dcb.name, cbStateOpen,
			failures, dcb.local.RemoteRecoveryTimeout())

		dcb.mu.Lock()
		dcb.remoteState = redisState
		dcb.remoteStateFetchedAt = time.Now()
		dcb.mu.Unlock()
		return false
	}

	// Step 3: 从 Redis 同步状态（慢路径，限频）
	if time.Since(dcb.remoteStateFetchedAt) > dcb.remoteCacheTTL {
		localState, localFailures := dcb.local.RemoteState()

		redisState, _ := SyncCircuitBreaker(dcb.name, localState,
			localFailures, dcb.local.RemoteRecoveryTimeout())

		dcb.mu.Lock()
		dcb.remoteState = redisState
		dcb.remoteStateFetchedAt = time.Now()
		dcb.mu.Unlock()

		// 如果 Redis 显示远程已熔断 → 同步本地熔断器
		if redisState == cbStateOpen {
			dcb.local.ForceOpen()
			return false
		}
	}

	return true
}

// Success 记录成功（同步到 Redis）
func (dcb *DistributedCircuitBreaker) Success() {
	dcb.local.Success()
	// 异步通知 Redis：状态已恢复
	go func() {
		SyncCircuitBreaker(dcb.name, cbStateClosed, 0, dcb.local.recoveryTimeout)
	}()
}

// Failure 记录失败（同步到 Redis）
func (dcb *DistributedCircuitBreaker) Failure() {
	dcb.local.Failure()
	// 检查本地是否已触发 OPEN
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

// IsOpen 检查是否熔断（本地 + 远程）
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

// ==================== DistributedCircuitBreakerGroup ====================

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

// DistributedBreakerMap 熔断器组映射（支持按服务名查找）
// 用于兼容现有 Handler 中的 breakerGroup 接口
type DistributedBreakerMap struct {
	group *DistributedCircuitBreakerGroup
}

func NewDistributedBreakerMap(group *DistributedCircuitBreakerGroup) *DistributedBreakerMap {
	return &DistributedBreakerMap{group: group}
}

// GetOrCreate 实现与现有 Handler 兼容的接口
func (m *DistributedBreakerMap) GetOrCreate(name string, threshold int, timeout time.Duration, halfOpenMax int) *DistributedCircuitBreaker {
	return m.group.GetOrCreate(name, threshold, timeout, halfOpenMax)
}
