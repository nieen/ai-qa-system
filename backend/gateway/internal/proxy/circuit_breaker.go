package proxy

import (
	"errors"
	"sync"
	"time"
)

// 熔断器状态
type state int

const (
	stateClosed   state = iota // 正常状态，请求通过
	stateOpen                  // 熔断状态，请求直接拒绝
	stateHalfOpen              // 半开状态，允许少量探测请求
)

// CircuitBreaker 熔断器
type CircuitBreaker struct {
	mu                  sync.RWMutex
	state               state
	failureCount        int
	consecutiveFailures int
	lastFailureTime     time.Time
	recoveryTimeout     time.Duration
	failureThreshold    int
	halfOpenMax         int
	halfOpenCount       int
}

// NewCircuitBreaker 创建熔断器
func NewCircuitBreaker(failureThreshold int, recoveryTimeout time.Duration, halfOpenMax int) *CircuitBreaker {
	return &CircuitBreaker{
		state:            stateClosed,
		failureThreshold: failureThreshold,
		recoveryTimeout:  recoveryTimeout,
		halfOpenMax:      halfOpenMax,
	}
}

// ErrCircuitOpen 熔断器打开错误
var ErrCircuitOpen = errors.New("服务熔断: 下游服务不可用")

// Allow 检查请求是否允许通过
func (cb *CircuitBreaker) Allow() bool {
	cb.mu.RLock()
	state := cb.state
	cb.mu.RUnlock()

	switch state {
	case stateOpen:
		// 检查是否到了恢复时间
		cb.mu.Lock()
		defer cb.mu.Unlock()
		if time.Since(cb.lastFailureTime) >= cb.recoveryTimeout {
			cb.state = stateHalfOpen
			cb.halfOpenCount = 0
			return true
		}
		return false
	case stateHalfOpen:
		cb.mu.Lock()
		defer cb.mu.Unlock()
		if cb.halfOpenCount < cb.halfOpenMax {
			cb.halfOpenCount++
			return true
		}
		return false
	default:
		return true
	}
}

// Success 记录成功
func (cb *CircuitBreaker) Success() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	switch cb.state {
	case stateHalfOpen:
		cb.state = stateClosed
		cb.consecutiveFailures = 0
		cb.halfOpenCount = 0
	case stateClosed:
		cb.consecutiveFailures = 0
	}
}

// Failure 记录失败
func (cb *CircuitBreaker) Failure() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	cb.consecutiveFailures++
	cb.lastFailureTime = time.Now()

	if cb.state == stateHalfOpen || cb.consecutiveFailures >= cb.failureThreshold {
		cb.state = stateOpen
	}
}

// IsOpen 检查熔断器是否打开
func (cb *CircuitBreaker) IsOpen() bool {
	cb.mu.RLock()
	defer cb.mu.RUnlock()
	return cb.state == stateOpen
}

// RemoteState 读取内部状态（供分布式熔断器使用）
func (cb *CircuitBreaker) RemoteState() (state int, failures int) {
	cb.mu.RLock()
	defer cb.mu.RUnlock()
	return int(cb.state), cb.consecutiveFailures
}

// RemoteRecoveryTimeout 读取恢复超时（供分布式熔断器使用）
func (cb *CircuitBreaker) RemoteRecoveryTimeout() time.Duration {
	return cb.recoveryTimeout
}

// Reset 手动重置熔断器
func (cb *CircuitBreaker) Reset() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.state = stateClosed
	cb.consecutiveFailures = 0
	cb.halfOpenCount = 0
}

// ForceOpen 强制将熔断器置为 OPEN 状态（用于分布式同步）
func (cb *CircuitBreaker) ForceOpen() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	if cb.state != stateOpen {
		cb.state = stateOpen
		cb.lastFailureTime = time.Now()
	}
}

// CircuitBreakerGroup 熔断器组 (每个服务一个)
type CircuitBreakerGroup struct {
	mu       sync.RWMutex
	breakers map[string]*CircuitBreaker
}

// NewCircuitBreakerGroup 创建熔断器组
func NewCircuitBreakerGroup() *CircuitBreakerGroup {
	return &CircuitBreakerGroup{
		breakers: make(map[string]*CircuitBreaker),
	}
}

// GetOrCreate 获取或创建熔断器
func (g *CircuitBreakerGroup) GetOrCreate(name string, threshold int, timeout time.Duration, halfOpenMax int) *CircuitBreaker {
	g.mu.RLock()
	cb, ok := g.breakers[name]
	g.mu.RUnlock()
	if ok {
		return cb
	}

	g.mu.Lock()
	defer g.mu.Unlock()
	if cb, ok := g.breakers[name]; ok {
		return cb
	}
	cb = NewCircuitBreaker(threshold, timeout, halfOpenMax)
	g.breakers[name] = cb
	return cb
}
