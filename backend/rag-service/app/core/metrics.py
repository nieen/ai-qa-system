"""
Prometheus 指标中间件 + LLM 专用监控
跟踪 HTTP 请求、Pipeline 步骤、LLM 调用、检索性能

指标分类:
  1. HTTP 层: 请求数/延迟/活跃连接
  2. Pipeline 层: 各步骤耗时
  3. LLM 层: 延迟/Token/降级/熔断
  4. 检索层: 向量/关键词检索分布
"""
import logging
import time
from typing import Optional
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

logger = logging.getLogger(__name__)

# ==================== 通用 HTTP 指标 ====================

if PROMETHEUS_AVAILABLE:
    http_requests_total = Counter(
        "rag_http_requests_total",
        "HTTP 请求总数",
        ["method", "endpoint", "status"],
    )

    http_request_duration_seconds = Histogram(
        "rag_http_request_duration_seconds",
        "HTTP 请求耗时 (秒)",
        ["method", "endpoint"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )

    active_requests = Gauge(
        "rag_active_requests",
        "当前活跃请求数",
    )

# ==================== 检索层指标 ====================

if PROMETHEUS_AVAILABLE:
    retrieval_requests_total = Counter(
        "rag_retrieval_requests_total",
        "检索请求总数按类型",
        ["type"],  # vector / keyword / merged
    )

    retrieval_latency_seconds = Histogram(
        "rag_retrieval_latency_seconds",
        "检索步骤耗时 (秒)",
        ["type"],  # vector / keyword / rerank
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
    )

    retrieval_hit_ratio = Gauge(
        "rag_retrieval_hit_ratio",
        "两路检索重叠率 (keyword_hits / total_merged)",
    )

# ==================== LLM 专用指标 ====================

if PROMETHEUS_AVAILABLE:
    # --- 调用量 ---
    llm_requests_total = Counter(
        "rag_llm_requests_total",
        "LLM 调用总数（按供应商+模型+结果）",
        ["provider", "model", "result"],  # result: success / error / fallback
    )

    llm_stream_requests_total = Counter(
        "rag_llm_stream_requests_total",
        "LLM 流式调用总数",
        ["provider", "result"],
    )

    # --- 延迟 ---
    llm_latency_seconds = Histogram(
        "rag_llm_latency_seconds",
        "LLM 调用延迟 (秒)",
        ["provider", "model", "mode"],  # mode: stream / non_stream
        buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
    )

    llm_first_token_latency_seconds = Histogram(
        "rag_llm_first_token_latency_seconds",
        "LLM 首 Token 延迟 (秒)",
        ["provider", "model"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
    )

    # --- Token 用量 ---
    llm_tokens_total = Counter(
        "rag_llm_tokens_total",
        "Token 消耗总数",
        ["provider", "model", "type"],  # type: prompt / completion / total
    )

    llm_tokens_per_request = Histogram(
        "rag_llm_tokens_per_request",
        "每次请求的 Token 数",
        ["provider", "model", "type"],
        buckets=(50, 100, 200, 500, 1000, 2000, 4000, 8000),
    )

    # --- 降级与熔断 ---
    llm_fallback_total = Counter(
        "rag_llm_fallback_total",
        "LLM 降级次数",
        ["from_provider", "to_provider"],
    )

    llm_circuit_breaker_state = Gauge(
        "rag_llm_circuit_breaker_state",
        "熔断器状态 (0=关闭 1=半开 2=打开)",
        ["provider"],
    )

    # --- 活跃调用 ---
    llm_active_calls = Gauge(
        "rag_llm_active_calls",
        "当前活跃的 LLM 调用数",
        ["provider"],
    )

# ==================== Pipeline 指标 ====================

if PROMETHEUS_AVAILABLE:
    pipeline_duration_seconds = Histogram(
        "rag_pipeline_duration_seconds",
        "Pipeline 各步骤耗时 (秒)",
        ["step"],  # embedding / vector_search / keyword_search / rrf_merge / rerank / llm / total
        buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    )

    pipeline_chunks_processed = Histogram(
        "rag_pipeline_chunks_processed",
        "Pipeline 各阶段处理的 Chunk 数",
        ["stage"],  # retrieved / reranked / final
        buckets=(1, 3, 5, 10, 20, 30, 50, 100),
    )

# ==================== 指标记录辅助函数 ====================


def record_llm_call(
    provider: str,
    model: str,
    result: str,
    latency_ms: float,
    tokens_total: int = 0,
    tokens_prompt: int = 0,
    tokens_completion: int = 0,
):
    """记录 LLM 调用指标"""
    if not PROMETHEUS_AVAILABLE:
        return

    llm_requests_total.labels(provider=provider, model=model, result=result).inc()
    llm_latency_seconds.labels(provider=provider, model=model, mode="non_stream").observe(latency_ms / 1000.0)

    if tokens_total:
        llm_tokens_total.labels(provider=provider, model=model, type="total").inc(tokens_total)
        llm_tokens_per_request.labels(provider=provider, model=model, type="total").observe(tokens_total)
    if tokens_prompt:
        llm_tokens_total.labels(provider=provider, model=model, type="prompt").inc(tokens_prompt)
    if tokens_completion:
        llm_tokens_total.labels(provider=provider, model=model, type="completion").inc(tokens_completion)


def record_llm_stream_call(
    provider: str,
    result: str,
    latency_ms: float,
    first_token_latency_ms: float = 0,
):
    """记录 LLM 流式调用指标"""
    if not PROMETHEUS_AVAILABLE:
        return

    llm_stream_requests_total.labels(provider=provider, result=result).inc()
    llm_latency_seconds.labels(provider=provider, model="stream", mode="stream").observe(latency_ms / 1000.0)
    if first_token_latency_ms:
        llm_first_token_latency_seconds.labels(provider=provider, model="stream").observe(
            first_token_latency_ms / 1000.0
        )


def record_llm_fallback(from_provider: str, to_provider: str):
    """记录 LLM 降级"""
    if not PROMETHEUS_AVAILABLE:
        return
    llm_fallback_total.labels(from_provider=from_provider, to_provider=to_provider).inc()


def record_circuit_breaker_state(provider: str, state: int):
    """
    记录熔断器状态
    Args:
        provider: 供应商名称
        state: 0=关闭, 1=半开, 2=打开
    """
    if not PROMETHEUS_AVAILABLE:
        return
    llm_circuit_breaker_state.labels(provider=provider).set(state)


def record_retrieval(type_: str, latency_ms: float = 0):
    """记录检索指标"""
    if not PROMETHEUS_AVAILABLE:
        return
    retrieval_requests_total.labels(type=type_).inc()
    if latency_ms:
        retrieval_latency_seconds.labels(type=type_).observe(latency_ms / 1000.0)


def record_pipeline_step(step: str, duration_ms: float):
    """记录 Pipeline 步骤耗时"""
    if not PROMETHEUS_AVAILABLE:
        return
    pipeline_duration_seconds.labels(step=step).observe(duration_ms / 1000.0)


def record_pipeline_chunks(stage: str, count: int):
    """记录 Pipeline 各阶段 Chunk 数"""
    if not PROMETHEUS_AVAILABLE:
        return
    pipeline_chunks_processed.labels(stage=stage).observe(count)


# ==================== 中间件 ====================


class MetricsMiddleware(BaseHTTPMiddleware):
    """Prometheus 指标采集中间件"""

    async def dispatch(self, request: Request, call_next):
        if not PROMETHEUS_AVAILABLE:
            return await call_next(request)

        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        endpoint = request.url.path
        if endpoint.startswith("/api/v1/knowledge-bases/"):
            parts = endpoint.split("/")
            if len(parts) >= 6:
                parts[4] = "{kb_id}"
            endpoint = "/".join(parts)

        active_requests.inc()
        start = time.time()

        try:
            response = await call_next(request)
            status = str(response.status_code)
            http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
            return response
        except Exception as e:
            http_requests_total.labels(method=method, endpoint=endpoint, status="500").inc()
            raise
        finally:
            http_request_duration_seconds.labels(
                method=method, endpoint=endpoint
            ).observe(time.time() - start)
            active_requests.dec()


def register_metrics_endpoint(app: FastAPI, prefix: str = ""):
    """注册 /metrics 端点"""
    if not PROMETHEUS_AVAILABLE:
        logger.warning("prometheus_client 未安装，指标端点不可用")
        return

    @app.get(f"{prefix}/metrics")
    async def metrics():
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    app.add_middleware(MetricsMiddleware)
    logger.info("Prometheus 指标端点已注册: /metrics ({name})")
    logger.info("  LLM 指标: llm_requests_total / llm_latency_seconds / llm_tokens_total / llm_fallback_total / llm_circuit_breaker_state / llm_active_calls")
    logger.info("  检索指标: retrieval_requests_total / retrieval_latency_seconds")
    logger.info("  Pipeline 指标: pipeline_duration_seconds / pipeline_chunks_processed")
