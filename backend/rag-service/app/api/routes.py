"""
RAG 服务 API 路由
仅处理 HTTP 请求/响应序列化，业务逻辑委托给 Pipeline + Container

认证说明:
  用户认证由 Go API 网关直接连接 PostgreSQL 处理（登录/注册/用户管理），
  RAG 服务不参与认证。已认证的用户信息通过 X-User-ID / X-User-Role Header 透传。

异步任务策略:
  - 实时问答 → async/await + SSE 流式
  - 文档索引 → Redis Streams (支持多副本、重试、持久化)
  - 批量处理 → 独立的 Worker 进程消费 Stream
"""
import json
import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import get_vector_store, get_pipeline, get_llm_router
from app.core.database import get_db
from app.core.event_bus import event_bus, STREAM_DOC_INGESTION, GROUP_DOC_WORKERS
from config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== 请求/响应模型 ====================


class ChatRequest(BaseModel):
    question: str
    conversation_id: Optional[str] = None
    history: Optional[List[dict]] = None


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = ""


# 注意: 认证模型 (LoginRequest/RegisterRequest) 在 Go 网关层处理


# ==================== 知识库管理 ====================


@router.get("/knowledge-bases")
async def list_knowledge_bases():
    return {
        "data": [{"id": "default", "name": "默认知识库", "document_count": 0, "status": "active"}],
        "total": 1,
    }


@router.post("/knowledge-bases")
async def create_knowledge_base(req: KnowledgeBaseCreate):
    kb_id = str(uuid.uuid4())
    vector_store = get_vector_store()
    await vector_store.create_collection(kb_id)
    return {"id": kb_id, "name": req.name, "status": "active"}


@router.get("/knowledge-bases/{kb_id}")
async def get_knowledge_base(kb_id: str):
    return {"id": kb_id, "name": "默认知识库", "status": "active"}


# ==================== 文档管理 ====================


@router.get("/knowledge-bases/{kb_id}/documents")
async def list_documents(kb_id: str):
    return {"data": [], "total": 0}


@router.post("/knowledge-bases/{kb_id}/documents/upload")
async def upload_document(
    kb_id: str,
    file: UploadFile = File(...),
):
    """
    上传文档 (通过 Redis Streams 异步索引)

    流程:
      1. 保存文件到临时目录 → 发布消息到 Redis Stream
      2. 立即返回 "processing" 状态
      3. Worker 进程消费 Stream: 解析 → 向量化 → 存储到 Milvus
      4. Worker 发布完成状态到 status Stream
      5. 前端可通过 /documents/{doc_id}/status 轮询结果

    多副本部署:
      - 多个 Worker 在同一消费者组中竞争消费
      - 崩溃 Worker 的任务被其他 Worker 认领 (XCLAIM)
      - 超过 MAX_DELIVERY_COUNT 的消息标记为死信

    支持格式: pdf, docx, md, html, txt
    """
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    file_type = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "txt"
    supported_types = {"pdf", "docx", "doc", "md", "html", "htm", "txt"}
    if file_type not in supported_types:
        raise HTTPException(400, f"不支持的文件类型: {file_type}")

    import os
    os.makedirs("tmp", exist_ok=True)
    tmp_path = f"tmp/{uuid.uuid4()}_{file.filename}"
    content = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(content)

    doc_id = str(uuid.uuid4())

    # 发布任务到 Redis Stream
    msg_id = await event_bus.publish(
        STREAM_DOC_INGESTION,
        "doc.index",
        {
            "kb_id": kb_id,
            "doc_id": doc_id,
            "file_path": tmp_path,
            "file_type": file_type,
            "file_name": file.filename,
        },
    )

    if msg_id:
        logger.info(f"文档索引任务已入队: {file.filename} -> stream_id={msg_id}")
        status_msg = "文档已加入索引队列 (Redis Streams)"
    else:
        logger.warning(f"事件总线不可用，文件将不会被索引: {file.filename}")
        status_msg = "文档已保存但事件总线不可用，请检查 Redis 连接"

    return {
        "id": doc_id,
        "title": file.filename,
        "file_type": file_type,
        "status": "processing",
        "message": status_msg,
    }


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}")
async def delete_document(kb_id: str, doc_id: str):
    vector_store = get_vector_store()
    await vector_store.delete_by_document(kb_id, doc_id)
    return {"message": "删除成功"}


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/status")
async def get_document_status(kb_id: str, doc_id: str):
    """
    查询文档索引状态
    从 Redis Streams 状态 Stream 中查询最新状态
    状态: processing / completed / failed
    """
    status = await event_bus.get_doc_status(doc_id)
    if status:
        return {"id": doc_id, **status}
    return {"id": doc_id, "status": "queued", "message": "文档正在队列中等待处理"}


# ==================== 核心问答 (使用 Pipeline) ====================


@router.post("/knowledge-bases/{kb_id}/chat")
async def chat(kb_id: str, req: ChatRequest):
    """
    知识库问答 (流式 SSE)

    使用 QueryPipeline 执行完整 RAG 流程:
      Phase 1: NaiveRAGPipeline (检索 → 重排序 → 生成)
      Phase 2: AgenticRAGPipeline (计划 → 检索 → 反思 → 生成)
    """
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "问题不能为空")

    pipeline = get_pipeline()

    async def generate():
        async for event in pipeline.execute(
            question=question,
            kb_id=kb_id,
            conversation_id=req.conversation_id,
            history=req.history,
        ):
            if event.type == "llm.token":
                yield f"data: {json.dumps({'type': 'token', 'content': event.data['content']})}\n\n"

            elif event.type == "retrieval.merged":
                yield f"data: {json.dumps({
                    'type': 'metadata',
                    'vector_count': event.data['vector_count'],
                    'keyword_count': event.data['keyword_count'],
                    'merged_count': event.data['merged_count'],
                    'status': 'retrieved',
                })}\n\n"

            elif event.type == "pipeline.done":
                yield f"data: {json.dumps({
                    'type': 'done',
                    'conversation_id': event.data['conversation_id'],
                    'model': event.data['model'],
                    'is_fallback': event.data['is_fallback'],
                    'sources': event.data['sources'],
                })}\n\n"

            elif event.type == "llm.error":
                yield f"data: {json.dumps({'type': 'error', 'content': event.data['content']})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== LLM 状态 ====================


@router.get("/llm/status")
async def get_llm_status():
    """查看 LLM 供应商状态"""
    llm_router = get_llm_router()
    health = await llm_router.check_health()
    return {
        **health,
        "max_total_tokens": settings.LLM_MAX_TOTAL_TOKENS,
        "fallback_enabled": settings.LLM_FALLBACK_ENABLED,
        "timeout": settings.LLM_TIMEOUT,
        "circuit_breaker_threshold": settings.LLM_CIRCUIT_BREAKER_THRESHOLD,
    }


@router.post("/llm/reset")
async def reset_llm():
    """手动重置 LLM 到主模型"""
    llm_router = get_llm_router()
    await llm_router.reset()
    return {"message": "LLM 已重置到主模型"}


# ==================== 用户 & 管理 ====================

# 注意: 用户认证和用户管理 (登录/注册/用户列表/用户信息) 由 Go 网关直接处理，
# RAG 服务只保留与知识库能力相关的管理端点。

@router.get("/admin/audit-logs")
async def get_audit_logs():
    """管理员 - 审计日志"""
    return {"data": [], "total": 0}
