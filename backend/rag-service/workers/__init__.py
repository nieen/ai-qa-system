"""
Worker 进程
独立于 FastAPI 主进程运行，通过 Redis Streams 接收任务
支持多副本部署: 通过消费者组自动负载均衡
"""
