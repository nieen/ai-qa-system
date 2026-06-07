"""
Worker Prometheus 指标

指标通过 prometheus_client 进程内记录。暴露方式（任选其一）：
  1. 多进程模式: prometheus_client 多进程目录 + RAG 服务 /metrics 统一输出
  2. Pushgateway: Worker 主动推送指标到 Pushgateway
  3. 独立端口: 调用 init_worker_metrics(metrics_port=9101) 启动 HTTP 服务

当前默认不启动独立 HTTP 服务，仅记录指标到进程内。
"""
import logging
from typing import Optional

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

logger = logging.getLogger("worker-metrics")

# ==================== 指标定义 ====================

if PROMETHEUS_AVAILABLE:

    # --- 消息处理量 ---
    worker_messages_total = Counter(
        "rag_worker_messages_total",
        "Worker 处理的消息总数",
        ["worker_id", "status"],  # status: success / failed / skipped
    )

    # --- 处理延迟 ---
    worker_message_duration_seconds = Histogram(
        "rag_worker_message_duration_seconds",
        "单条消息处理耗时 (秒)",
        ["worker_id", "message_type"],
        buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    )

    # --- 文档处理细分 ---
    worker_document_processing_duration_seconds = Histogram(
        "rag_worker_document_processing_duration_seconds",
        "文档处理各步骤耗时 (秒)",
        ["worker_id", "step"],  # step: download / parse / embed / insert / total
        buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    )

    # --- 当前待处理消息数 ---
    worker_pending_messages = Gauge(
        "rag_worker_pending_messages",
        "当前 Redis Stream 中待处理的消息数",
        ["stream", "group"],
    )

    # --- Worker 活跃状态 ---
    worker_up = Gauge(
        "rag_worker_up",
        "Worker 是否正在运行 (1=运行, 0=停止)",
        ["worker_id"],
    )

    # --- 空闲检测 ---
    worker_idle_loops = Gauge(
        "rag_worker_idle_loops",
        "连续空闲循环次数（值越大说明越空闲）",
        ["worker_id"],
    )


def init_worker_metrics(worker_id: str, metrics_port: Optional[int] = None):
    """初始化 Worker 指标

    Args:
        worker_id: Worker 标识
        metrics_port: 可选，指定时启动 HTTP 服务暴露 /metrics。
                     不指定则不启动 HTTP 服务，指标仅在进程内记录。
    """
    if not PROMETHEUS_AVAILABLE:
        logger.warning("prometheus_client 未安装，指标不可用")
        return

    # 设置 Worker 活跃状态
    worker_up.labels(worker_id=worker_id).set(1)

    if metrics_port is not None:
        try:
            start_http_server(metrics_port)
            logger.info(f"Prometheus 指标 HTTP 服务已启动: 端口 {metrics_port}")
        except Exception as e:
            logger.warning(f"Prometheus 指标 HTTP 服务启动失败: {e}")


def set_worker_stopped(worker_id: str):
    """标记 Worker 停止"""
    if PROMETHEUS_AVAILABLE:
        worker_up.labels(worker_id=worker_id).set(0)


def record_message_processed(worker_id: str, status: str, duration_ms: float):
    """记录消息处理结果"""
    if not PROMETHEUS_AVAILABLE:
        return
    worker_messages_total.labels(worker_id=worker_id, status=status).inc()
    worker_message_duration_seconds.labels(
        worker_id=worker_id, message_type="doc.index"
    ).observe(duration_ms / 1000.0)


def record_processing_step(worker_id: str, step: str, duration_ms: float):
    """记录文档处理各步骤耗时"""
    if not PROMETHEUS_AVAILABLE:
        return
    worker_document_processing_duration_seconds.labels(
        worker_id=worker_id, step=step
    ).observe(duration_ms / 1000.0)


def update_pending_messages(stream: str, group: str, count: int):
    """更新待处理消息数"""
    if PROMETHEUS_AVAILABLE:
        worker_pending_messages.labels(stream=stream, group=group).set(count)


def update_idle_loops(worker_id: str, count: int):
    """更新空闲循环计数"""
    if PROMETHEUS_AVAILABLE:
        worker_idle_loops.labels(worker_id=worker_id).set(count)
