package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"math/rand"
	"net/http"
	"strings"
	"time"

	"github.com/ai-qa-system/gateway/internal/config"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// RAGProxyClient RAG 服务代理客户端
// 封装熔断器、重试、审计日志等逻辑
type RAGProxyClient struct {
	baseURL      string
	client       *http.Client
	logger       *zap.SugaredLogger
	breakerGroup *DistributedCircuitBreakerGroup
	cfg          *config.Config
}

// NewRAGProxyClient 创建 RAG 代理客户端
func NewRAGProxyClient(cfg *config.Config, logger *zap.SugaredLogger) *RAGProxyClient {
	return &RAGProxyClient{
		baseURL: cfg.Services.RAGService.BaseURL + "/api/v1",
		cfg:     cfg,
		logger:  logger,
		client: &http.Client{
			Timeout: 120 * time.Second,
			Transport: &http.Transport{
				MaxIdleConns:        100,
				MaxIdleConnsPerHost: 20,
				IdleConnTimeout:     90 * time.Second,
			},
		},
		breakerGroup: NewDistributedCircuitBreakerGroup(),
	}
}

// buildURL 构建完整的 RAG 服务 URL
func (p *RAGProxyClient) buildURL(path string) string {
	return p.baseURL + path
}

// getCircuitBreaker 获取或创建熔断器
func (p *RAGProxyClient) getCircuitBreaker() *DistributedCircuitBreaker {
	cbCfg := p.cfg.Services.RAGService.CircuitBreaker
	if !cbCfg.Enabled {
		noopLocal := NewCircuitBreaker(9999, 24*time.Hour, 9999)
		return NewDistributedCircuitBreaker("rag-service", noopLocal)
	}

	timeout, err := time.ParseDuration(cbCfg.RecoveryTimeout)
	if err != nil {
		timeout = 30 * time.Second
	}

	return p.breakerGroup.GetOrCreate(
		"rag-service",
		cbCfg.FailureCount,
		timeout,
		cbCfg.HalfOpenMax,
	)
}

// isCircuitOpen 检查熔断器是否已打开；如果已熔断，自动写入 503 响应并返回 true
func (p *RAGProxyClient) isCircuitOpen(c *gin.Context, path, method string) bool {
	cb := p.getCircuitBreaker()
	if !cb.Allow() {
		p.logger.Warnw("熔断器阻止请求", "path", path, "method", method)
		c.JSON(503, gin.H{
			"error": "服务暂不可用 (熔断)",
			"code":  "CIRCUIT_OPEN",
		})
		return true
	}
	return false
}

// setRAGHeaders 设置代理到 RAG 服务的通用请求头
func setRAGHeaders(req *http.Request, c *gin.Context) {
	req.Header.Set("X-User-ID", c.GetString("user_id"))
	req.Header.Set("X-User-Role", c.GetString("user_role"))
	req.Header.Set("X-Request-ID", c.GetString("request_id"))
	req.Header.Set("Content-Type", "application/json")
}

// extractAuditAction 从 HTTP 方法和路径提取审计动作
func extractAuditAction(method, path string) string {
	action := "kb."
	switch method {
	case "POST":
		action += "create"
	case "PUT":
		action += "update"
	case "DELETE":
		action += "delete"
	default:
		action += strings.ToLower(method)
	}

	if strings.Contains(path, "/documents/") {
		action = strings.Replace(action, "kb.", "document.", 1)
	}
	if strings.Contains(path, "/chat") {
		action = "kb.chat"
	}
	return action
}

// extractAuditResource 从路径提取资源类型
func extractAuditResource(path string) string {
	switch {
	case strings.Contains(path, "/knowledge-bases") && !strings.Contains(path, "/documents"):
		return "knowledge_base"
	case strings.Contains(path, "/documents"):
		return "document"
	case strings.Contains(path, "/conversations"):
		return "conversation"
	default:
		return "kb"
	}
}

// extractAuditResourceID 从 Gin 路由参数中提取资源 ID
func extractAuditResourceID(c *gin.Context) string {
	for _, param := range c.Params {
		switch param.Key {
		case "id", "kbId", "docId", "convId":
			if param.Value != "" {
				return param.Value
			}
		}
	}
	return ""
}

// Request 将请求代理到 RAG 服务 (带熔断和重试)
func (p *RAGProxyClient) Request(c *gin.Context, method, path string, body interface{}) {
	ragURL := p.buildURL(path)

	if p.isCircuitOpen(c, path, method) {
		return
	}

	var jsonBody []byte
	if body != nil {
		var err error
		jsonBody, err = json.Marshal(body)
		if err != nil {
			p.logger.Errorf("JSON 序列化失败: %v", err)
			c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
			return
		}
	}

	var rawBody []byte
	if body == nil && (method == "POST" || method == "PUT") {
		var err error
		rawBody, err = io.ReadAll(c.Request.Body)
		if err != nil {
			p.logger.Errorf("读取请求体失败: %v", err)
			c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
			return
		}
	}

	maxRetries := p.cfg.Services.RAGService.RetryCount
	var lastErr error
	var resp *http.Response

	for attempt := 0; attempt <= maxRetries; attempt++ {
		var reqBody io.Reader
		if jsonBody != nil {
			reqBody = bytes.NewReader(jsonBody)
		} else if rawBody != nil {
			reqBody = bytes.NewReader(rawBody)
		}

		ctx := c.Request.Context()
		req, err := http.NewRequestWithContext(ctx, method, ragURL, reqBody)
		if err != nil {
			c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
			return
		}

		setRAGHeaders(req, c)

		resp, lastErr = p.client.Do(req)
		if lastErr == nil {
			break
		}

		if ctx.Err() != nil {
			p.logger.Warnw("客户端断开连接", "path", path)
			return
		}

		if attempt < maxRetries {
			backoff := time.Duration(math.Pow(2, float64(attempt))) * 200 * time.Millisecond
			jitter := time.Duration(rand.Int63n(int64(backoff / 2)))
			time.Sleep(backoff + jitter)
			p.logger.Infow("重试请求",
				"attempt", attempt+1,
				"max", maxRetries,
				"path", path,
			)
		}
	}

	if lastErr != nil {
		p.logger.Errorf("RAG 服务请求失败 (已重试 %d 次): %v", maxRetries, lastErr)
		p.getCircuitBreaker().Failure()
		c.JSON(502, gin.H{"error": "服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 500 {
		p.getCircuitBreaker().Failure()
	} else {
		p.getCircuitBreaker().Success()
	}

	bodyBytes, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, resp.Header.Get("Content-Type"), bodyBytes)
}

// RequestStream 流式代理到 RAG 服务 (SSE)，带重试
func (p *RAGProxyClient) RequestStream(c *gin.Context, method, path string, body interface{}) {
	ragURL := p.buildURL(path)

	if p.isCircuitOpen(c, path, method) {
		return
	}

	jsonData, err := json.Marshal(body)
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}

	ctx := c.Request.Context()
	req, err := http.NewRequestWithContext(ctx, method, ragURL, bytes.NewReader(jsonData))
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}

	setRAGHeaders(req, c)

	resp, err := p.client.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			p.logger.Infow("SSE 流中断: 客户端断开", "path", path)
			return
		}
		p.logger.Errorf("SSE 代理请求失败: %v", err)
		p.getCircuitBreaker().Failure()
		select {
		case <-ctx.Done():
			return
		default:
			c.JSON(502, gin.H{"error": "服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		}
		return
	}
	defer resp.Body.Close()

	p.getCircuitBreaker().Success()

	c.Status(resp.StatusCode)
	for k, v := range resp.Header {
		for _, hv := range v {
			c.Header(k, hv)
		}
	}
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	buf := make([]byte, 4096)
	for {
		select {
		case <-ctx.Done():
			p.logger.Infow("SSE 流终止: 客户端断开", "path", path)
			return
		default:
			n, readErr := resp.Body.Read(buf)
			if n > 0 {
				if _, writeErr := c.Writer.Write(buf[:n]); writeErr != nil {
					return
				}
				c.Writer.Flush()
			}
			if readErr != nil {
				return
			}
		}
	}
}

// UploadFile 代理文件上传到 RAG 服务
func (p *RAGProxyClient) UploadFile(c *gin.Context, kbID string) {
	ragURL := fmt.Sprintf("%s/knowledge-bases/%s/documents/upload", p.baseURL, kbID)

	file, header, err := c.Request.FormFile("file")
	if err != nil {
		if err.Error() == "http: request body too large" {
			c.JSON(413, gin.H{"error": "文件过大", "code": "FILE_TOO_LARGE"})
			return
		}
		c.JSON(400, gin.H{"error": "请上传文件", "code": "FILE_REQUIRED"})
		return
	}
	defer file.Close()

	req, err := http.NewRequest("POST", ragURL, file)
	if err != nil {
		c.JSON(500, gin.H{"error": "内部错误", "code": "INTERNAL_ERROR"})
		return
	}
	req.Header.Set("Content-Type", header.Header.Get("Content-Type"))
	req.Header.Set("X-User-ID", c.GetString("user_id"))

	resp, err := p.client.Do(req)
	if err != nil {
		c.JSON(502, gin.H{"error": "服务暂不可用", "code": "SERVICE_UNAVAILABLE"})
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, resp.Header.Get("Content-Type"), body)
}

// CheckHealth 检查下游 RAG 服务健康状态
func (p *RAGProxyClient) CheckHealth(c *gin.Context) {
	ragURL := p.cfg.Services.RAGService.BaseURL + "/health"

	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "GET", ragURL, nil)
	if err != nil {
		c.JSON(503, gin.H{
			"status":  "unhealthy",
			"service": "rag-service",
			"error":   err.Error(),
		})
		return
	}

	resp, err := p.client.Do(req)
	if err != nil {
		c.JSON(503, gin.H{
			"status":  "unhealthy",
			"service": "rag-service",
			"error":   err.Error(),
		})
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	c.Data(resp.StatusCode, "application/json", body)
}
