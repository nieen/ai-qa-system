package middleware

import (
	"expvar"
	"strconv"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

// Metrics 指标收集器 (使用 expvar，零外部依赖)
type Metrics struct {
	requestsTotal    atomic.Int64
	activeRequests   atomic.Int64
	errorTotal       atomic.Int64
	latencyTotalMs   atomic.Int64
	requestCount     atomic.Int64
	downstreamErrors atomic.Int64
}

// NewMetrics 创建指标收集器
func NewMetrics() *Metrics {
	m := &Metrics{}
	// 注册 expvar 变量
	expvar.Publish("gateway_requests_total", expvar.Func(func() interface{} {
		return m.requestsTotal.Load()
	}))
	expvar.Publish("gateway_active_requests", expvar.Func(func() interface{} {
		return m.activeRequests.Load()
	}))
	expvar.Publish("gateway_errors_total", expvar.Func(func() interface{} {
		return m.errorTotal.Load()
	}))
	expvar.Publish("gateway_downstream_errors_total", expvar.Func(func() interface{} {
		return m.downstreamErrors.Load()
	}))
	expvar.Publish("gateway_avg_latency_ms", expvar.Func(func() interface{} {
		count := m.requestCount.Load()
		if count == 0 {
			return 0
		}
		return m.latencyTotalMs.Load() / count
	}))
	return m
}

// MetricsMiddleware Prometheus 风格指标采集中间件
func (m *Metrics) MetricsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		// 排除指标端点自身
		if c.Request.URL.Path == "/debug/vars" {
			c.Next()
			return
		}

		m.activeRequests.Add(1)
		m.requestsTotal.Add(1)
		start := time.Now()

		c.Next()

		latency := time.Since(start).Milliseconds()
		m.latencyTotalMs.Add(latency)
		m.requestCount.Add(1)

		status := c.Writer.Status()
		if status >= 500 {
			m.errorTotal.Add(1)
		}

		m.activeRequests.Add(-1)
	}
}

// RecordDownstreamError 记录下游错误
func (m *Metrics) RecordDownstreamError() {
	m.downstreamErrors.Add(1)
}

// RecordDownstreamStatus 记录下游请求状态码
func (m *Metrics) RecordDownstreamStatus(service string, statusCode int) {
	expvarParam := "gateway_" + service + "_status_" + strconv.Itoa(statusCode)
	expvar.Publish(expvarParam, expvar.Func(func() interface{} {
		return statusCode
	}))
}

// MetricsHandler 返回 /metrics 的 Gin 处理器 (使用 expvar 替代 prometheus)
func MetricsHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Content-Type", "application/json; charset=utf-8")
		c.String(200, "{\n")
		c.String(200, "  \"gateway_version\": \"1.0.0\",\n")
		expvar.Do(func(kv expvar.KeyValue) {
			c.String(200, "  %q: %s,\n", kv.Key, kv.Value.String())
		})
		c.String(200, "  \"status\": \"ok\"\n")
		c.String(200, "}\n")
	}
}
