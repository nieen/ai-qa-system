"""
OpenTelemetry 分布式链路追踪配置

提供全链路追踪能力，覆盖:
  - HTTP 请求入口 (FastAPI 自动埋点)
  - HTTP 外部调用 (httpx 自动埋点)
  - RAG Pipeline 各步骤 (手动 Span)
  - LLM 调用 (手动 Span + 属性标注)
  - Redis 操作 (手动 Span)

导出方式: OTLP gRPC/HTTP (可配置)
"""
import logging
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

# 全局 Tracer
_tracer = None


def get_tracer():
    """获取全局 Tracer 实例"""
    global _tracer
    return _tracer


def setup_tracing(service_name: str = "rag-service") -> bool:
    """
    初始化 OpenTelemetry

    配置来源 settings.OTEL_*:
      - OTEL_ENABLED: 是否启用 (默认 True)
      - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP 接收端 (默认 http://localhost:4318)
      - OTEL_SERVICE_NAME: 服务名

    Returns:
        是否成功初始化
    """
    global _tracer

    if not settings.OTEL_ENABLED:
        logger.info("OpenTelemetry 追踪已禁用")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME

        # 资源定义
        resource = Resource.create({
            SERVICE_NAME: service_name,
            "service.version": "1.0.0",
            "deployment.environment": settings.APP_LOG_LEVEL,
        })

        # 创建 TracerProvider
        provider = TracerProvider(resource=resource)

        # 配置导出器
        endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
        if endpoint:
            _setup_otlp_exporter(provider, endpoint)

        # 设置全局 TracerProvider
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)

        # 自动埋点: FastAPI
        _instrument_fastapi()
        # 自动埋点: httpx
        _instrument_httpx()

        logger.info("OpenTelemetry 追踪初始化完成 (endpoint=%s)", endpoint or "stdout")
        return True

    except ImportError as e:
        logger.warning("OpenTelemetry 包未安装，追踪不可用: %s", e)
        logger.warning("如需启用: pip install opentelemetry-distro opentelemetry-exporter-otlp")
        return False
    except Exception as e:
        logger.warning("OpenTelemetry 初始化失败: %s", e)
        return False


def _setup_otlp_exporter(provider, endpoint: str):
    """配置 OTLP 导出器"""
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            insecure=True,  # 内网场景
        )
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        logger.info("OTLP gRPC 导出器已配置: %s", endpoint)
    except ImportError:
        # 降级: HTTP 导出
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint + "/v1/traces")
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            logger.info("OTLP HTTP 导出器已配置: %s", endpoint)
        except ImportError:
            logger.warning("OTLP 导出器未安装，追踪仅在进程中可见")


def _instrument_fastapi():
    """自动埋点 FastAPI"""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        # 延迟到 app 创建后 instrument，这里仅记录
        logger.debug("FastAPI 自动埋点已准备")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-fastapi 未安装")


def _instrument_httpx():
    """自动埋点 httpx"""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
        logger.debug("httpx 自动埋点已完成")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-httpx 未安装")


def instrument_app(app) -> bool:
    """在 FastAPI 应用上执行自动埋点"""
    if not settings.OTEL_ENABLED:
        return False

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI 自动埋点完成")
        return True
    except ImportError:
        logger.debug("OpenTelemetry FastAPI 埋点不可用")
        return False


def shutdown_tracing():
    """关闭追踪，刷新所有 Span"""
    global _tracer

    try:
        from opentelemetry import trace
        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
            logger.info("OpenTelemetry 追踪已关闭")
    except Exception as e:
        logger.debug("关闭追踪异常: %s", e)

    _tracer = None


# ==================== 手动 Span 辅助函数 ====================


def start_span(name: str, attributes: dict = None):
    """
    创建手动 Span

    用法:
        with start_span("embedding", {"text_length": len(text)}) as span:
            result = await embed(text)
            span.set_attribute("vector_dim", len(result))
    """
    tracer = get_tracer()
    if not tracer:
        # 返回一个 no-op span context manager
        from contextlib import nullcontext
        return nullcontext()

    return tracer.start_as_current_span(name, attributes=attributes)


def set_span_attribute(key: str, value):
    """设置当前 Span 属性 (线程安全)"""
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute(key, value)
    except Exception:
        pass


def record_exception(exc: Exception):
    """记录异常到当前 Span"""
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span.is_recording():
            span.record_exception(exc)
    except Exception:
        pass
