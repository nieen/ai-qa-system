package handler

import (
	"sync"
	"testing"
	"time"
)

func TestCircuitBreakerClosed(t *testing.T) {
	cb := NewCircuitBreaker(5, 10*time.Second, 3)

	if !cb.Allow() {
		t.Error("Closed 状态的熔断器应允许请求")
	}
	if cb.IsOpen() {
		t.Error("初始状态应为 Closed")
	}
}

func TestCircuitBreakerOpensAfterFailures(t *testing.T) {
	cb := NewCircuitBreaker(3, 10*time.Second, 3)

	// Closed: 允许
	// 连续失败 2 次
	cb.Failure()
	cb.Failure()

	if cb.IsOpen() {
		t.Error("3 次才触发熔断，目前 2 次不应打开")
	}

	// 第 3 次失败 → 熔断
	cb.Failure()

	if !cb.IsOpen() {
		t.Error("连续 3 次失败后熔断器应打开")
	}

	// Open: 不允许
	if cb.Allow() {
		t.Error("Open 状态的熔断器应拒绝请求")
	}
}

func TestCircuitBreakerHalfOpen(t *testing.T) {
	cb := NewCircuitBreaker(3, 50*time.Millisecond, 2)

	// 触发熔断
	cb.Failure()
	cb.Failure()
	cb.Failure()

	if !cb.IsOpen() {
		t.Fatal("熔断器应已打开")
	}

	// 等待恢复时间
	time.Sleep(60 * time.Millisecond)

	// 应进入 HalfOpen
	if !cb.Allow() {
		t.Error("恢复时间后 HalfOpen 应允许探测请求")
	}

	// HalfOpen 成功 → 关闭
	cb.Success()

	if cb.IsOpen() {
		t.Error("HalfOpen 成功后熔断器应关闭")
	}
}

func TestCircuitBreakerHalfOpenFailure(t *testing.T) {
	cb := NewCircuitBreaker(3, 100*time.Millisecond, 2)

	cb.Failure()
	cb.Failure()
	cb.Failure()

	time.Sleep(120 * time.Millisecond)

	// HalfOpen 允许
	cb.Allow()
	// HalfOpen 失败 → 回到 Open
	cb.Failure()

	if !cb.IsOpen() {
		t.Error("HalfOpen 失败后熔断器应重新打开")
	}
}

func TestCircuitBreakerConcurrent(t *testing.T) {
	cb := NewCircuitBreaker(10, time.Second, 5)

	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			cb.Allow()
			cb.Success()
		}()
	}
	wg.Wait()

	if cb.IsOpen() {
		t.Error("并发成功后熔断器不应打开")
	}
}

func TestCircuitBreakerReset(t *testing.T) {
	cb := NewCircuitBreaker(3, time.Second, 3)

	cb.Failure()
	cb.Failure()
	cb.Failure()

	if !cb.IsOpen() {
		t.Fatal("熔断器应已打开")
	}

	cb.Reset()
	if cb.IsOpen() {
		t.Error("Reset() 后熔断器应关闭")
	}
	if !cb.Allow() {
		t.Error("Reset() 后应允许请求")
	}
}

func TestCircuitBreakerGroup(t *testing.T) {
	g := NewCircuitBreakerGroup()

	cb1 := g.GetOrCreate("svc-a", 5, time.Second, 3)
	cb2 := g.GetOrCreate("svc-b", 3, time.Second, 3)
	cb1again := g.GetOrCreate("svc-a", 5, time.Second, 3)

	if cb1 != cb1again {
		t.Error("相同名称应返回同一实例")
	}
	if cb1 == cb2 {
		t.Error("不同名称应返回不同实例")
	}
}

func TestErrCircuitOpen(t *testing.T) {
	if ErrCircuitOpen.Error() == "" {
		t.Error("ErrCircuitOpen 应有错误信息")
	}
}
