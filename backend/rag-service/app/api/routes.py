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
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
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
    """聊天请求"""
    question: str
    conversation_id: Optional[str] = None
    history: Optional[List[dict]] = None


class KnowledgeBaseCreate(BaseModel):
    """创建知识库请求"""
    name: str
    description: Optional[str] = ""


class KnowledgeBaseResponse(BaseModel):
    """知识库信息"""
    id: str
    name: str
    status: str


class DocumentUploadResponse(BaseModel):
    """文档上传响应"""
    id: str
    title: str
    file_type: str
    status: str
    message: str


class LLMStatusResponse(BaseModel):
    """LLM 状态响应"""
    status: str
    primary: bool
    primary_model: str
    fallback_model: Optional[str] = None
    max_total_tokens: int
    fallback_enabled: bool
    timeout: float
    circuit_breaker_threshold: int


# 注意: 认证模型 (LoginRequest/RegisterRequest) 在 Go 网关层处理


# ==================== 知识库管理 ====================


@router.get(
    "/knowledge-bases",
    summary="获取知识库列表",
    description="返回所有可用的知识库列表及基本信息",
    tags=["知识库管理"],
    response_model=dict,
)
async def list_knowledge_bases():
    """获取所有知识库列表"""
    return {
        "data": [{"id": "default", "name": "默认知识库", "document_count": 0, "status": "active"}],
        "total": 1,
    }


@router.post(
    "/knowledge-bases",
    summary="创建知识库",
    description="创建一个新的知识库，并在向量数据库中创建对应的 Collection",
    tags=["知识库管理"],
    response_model=KnowledgeBaseResponse,
)
async def create_knowledge_base(req: KnowledgeBaseCreate):
    """创建新的知识库"""
    kb_id = str(uuid.uuid4())
    vector_store = get_vector_store()
    await vector_store.create_collection(kb_id)
    return {"id": kb_id, "name": req.name, "status": "active"}


@router.get(
    "/knowledge-bases/{kb_id}",
    summary="获取知识库详情",
    description="根据知识库 ID 获取详细信息",
    tags=["知识库管理"],
    response_model=KnowledgeBaseResponse,
)
async def get_knowledge_base(kb_id: str):
    """获取指定知识库的信息"""
    return {"id": kb_id, "name": "默认知识库", "status": "active"}


# ==================== 文档管理 ====================


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    summary="获取文档列表",
    description="获取指定知识库下的所有文档列表",
    tags=["文档管理"],
)
async def list_documents(kb_id: str):
    """获取知识库中的文档列表"""
    return {"data": [], "total": 0}


@router.post(
    "/knowledge-bases/{kb_id}/documents/upload",
    summary="上传文档",
    description="""
    上传文档并通过 Redis Streams 异步索引。

    **流程:**
    1. 保存文件到临时目录 → 发布消息到 Redis Stream
    2. 立即返回 "processing" 状态
    3. Worker 进程消费 Stream: 解析 → 向量化 → 存储到 Milvus

    **支持格式:** pdf, docx, md, html, txt
    """,
    tags=["文档管理"],
    response_model=DocumentUploadResponse,
)
async def upload_document(
    kb_id: str,
    file: UploadFile = File(...),
):
    """
    上传文档 (通过 Redis Streams 异步索引)
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


@router.delete(
    "/knowledge-bases/{kb_id}/documents/{doc_id}",
    summary="删除文档",
    description="从知识库中删除指定文档及其向量数据",
    tags=["文档管理"],
)
async def delete_document(kb_id: str, doc_id: str):
    """删除知识库中的文档"""
    vector_store = get_vector_store()
    await vector_store.delete_by_document(kb_id, doc_id)
    return {"message": "删除成功"}


@router.get(
    "/knowledge-bases/{kb_id}/documents/{doc_id}/status",
    summary="查询文档索引状态",
    description="查询文档的异步索引处理状态: processing / completed / failed / queued",
    tags=["文档管理"],
)
async def get_document_status(kb_id: str, doc_id: str):
    """查询文档索引状态"""
    status = await event_bus.get_doc_status(doc_id)
    if status:
        return {"id": doc_id, **status}
    return {"id": doc_id, "status": "queued", "message": "文档正在队列中等待处理"}


# ==================== 核心问答 (使用 Pipeline) ====================


@router.post(
    "/knowledge-bases/{kb_id}/chat",
    summary="知识库问答 (SSE 流式)",
    description="""
    执行完整 RAG 流程进行问答，返回 SSE (Server-Sent Events) 流式响应。

    **事件类型:**
    - `token`: LLM 生成的文本片段
    - `metadata`: 检索结果统计信息
    - `error`: 处理过程中的错误信息
    - `done`: 问答完成，包含来源引用

    **流程:**
    1. 查询向量化 (BGE-M3 / text2vec)
    2. 向量检索 (Milvus) + BM25 关键词检索
    3. RRF 融合 + Reranker 重排序
    4. LLM 流式生成 (支持主/备模型自动降级)
    """,
    tags=["问答"],
)
async def chat(kb_id: str, req: ChatRequest, http_request: Request):
    """知识库问答 (SSE 流式响应)"""
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "问题不能为空")

    # 透传 Go 网关传递的 X-Request-ID，保持链路追踪完整性
    request_id = http_request.headers.get("X-Request-ID", "")

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

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if request_id:
        headers["X-Request-ID"] = request_id

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=headers,
    )


# ==================== LLM 状态 ====================


@router.get(
    "/llm/status",
    summary="查看 LLM 供应商状态",
    description="查看当前 LLM 供应商的健康状态、主/备模型信息、熔断器状态等",
    tags=["LLM 管理"],
    response_model=LLMStatusResponse,
)
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


@router.post(
    "/llm/reset",
    summary="重置 LLM 到主模型",
    description="手动将 LLM 从备用模型切换回主模型",
    tags=["LLM 管理"],
)
async def reset_llm():
    """手动重置 LLM 到主模型"""
    llm_router = get_llm_router()
    await llm_router.reset()
    return {"message": "LLM 已重置到主模型"}


# ==================== 管理 ====================

# 注意: 用户管理由 Go 网关处理，RAG 服务只保留知识库相关管理端点。

@router.get(
    "/admin/audit-logs",
    summary="查看审计日志",
    description="管理员查看系统审计日志（注意：完整审计日志通过网关 /admin/audit-logs 查询）",
    tags=["管理"],
)
async def get_audit_logs():
    """管理员 - 审计日志"""
    return {"data": [], "total": 0}
