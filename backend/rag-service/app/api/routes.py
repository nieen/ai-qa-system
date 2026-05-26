"""
RAG 服务 API 路由 (重构版)
仅处理 HTTP 请求/响应序列化，业务逻辑委托给 Pipeline + Container

异步任务策略:
  - 实时问答 → async/await + SSE 流式 (不走 Celery)
  - 文档索引 → FastAPI BackgroundTasks (轻量, 零额外依赖)
  - 批量处理 → 由外部编排或独立的 Worker 进程处理
"""
import json
import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.container import get_vector_store, get_embedding_model, get_pipeline, get_llm_router
from app.ingestion.document_processor import document_processor
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


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""
    email: Optional[str] = ""


# ==================== 认证 ====================


@router.post("/auth/login")
async def login(req: LoginRequest):
    if req.username == "admin" and req.password == "admin123":
        return {
            "token": "dev-token",
            "user": {"id": "1", "username": "admin", "role": "admin"},
        }
    raise HTTPException(401, "用户名或密码错误")


@router.post("/auth/register")
async def register(req: RegisterRequest):
    return {"message": "注册成功", "user": {"id": str(uuid.uuid4()), "username": req.username}}


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
    bg: BackgroundTasks = BackgroundTasks(),
):
    """
    上传文档 (异步索引)

    流程:
      1. 保存文件到临时目录 → 立即返回 "processing" 状态
      2. 后台任务: 解析 → 向量化 → 存储到 Milvus

    支持格式: pdf, docx, md, html, txt
    """
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    file_type = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "txt"
    supported_types = {"pdf", "docx", "doc", "md", "html", "htm", "txt"}
    if file_type not in supported_types:
        raise HTTPException(400, f"不支持的文件类型: {file_type}")

    import tempfile, os
    os.makedirs("tmp", exist_ok=True)
    tmp_path = f"tmp/{uuid.uuid4()}_{file.filename}"
    content = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(content)

    doc_id = str(uuid.uuid4())

    # 后台异步索引 (FastAPI BackgroundTasks, 零额外依赖)
    bg.add_task(_index_document_background, kb_id, doc_id, tmp_path, file_type, file.filename)

    return {
        "id": doc_id,
        "title": file.filename,
        "file_type": file_type,
        "status": "processing",
        "message": "文档已加入索引队列，将在后台处理",
    }


async def _index_document_background(
    kb_id: str,
    doc_id: str,
    file_path: str,
    file_type: str,
    filename: str,
):
    """
    后台文档索引任务

    在 FastAPI BackgroundTasks 中运行，不阻塞 API 响应。
    多副本部署时: 每个副本各自处理自己的后台任务。
    """
    import os
    from app.core.container import get_vector_store, get_embedding_model
    from app.core.protocols import Document as DocModel

    logger.info(f"开始后台索引文档: {filename}")

    try:
        chunks = await document_processor.process(file_path, file_type)
        if not chunks:
            logger.warning(f"文档内容为空: {filename}")
            return

        texts = [c["content"] for c in chunks]
        embedding_model = get_embedding_model()
        embeddings = await embedding_model.embed_documents(texts)

        documents = [
            DocModel(
                chunk_id=str(uuid.uuid4()),
                document_id=doc_id,
                kb_id=kb_id,
                chunk_index=c["chunk_index"],
                content=c["content"],
                metadata=c["metadata"],
            )
            for c in chunks
        ]

        vector_store = get_vector_store()
        await vector_store.insert(kb_id, documents, embeddings)

        logger.info(f"后台索引完成: {filename} → {len(chunks)} 个块")
    except Exception as e:
        logger.error(f"后台索引失败 [{filename}]: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}")
async def delete_document(kb_id: str, doc_id: str):
    vector_store = get_vector_store()
    await vector_store.delete_by_document(kb_id, doc_id)
    return {"message": "删除成功"}


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/status")
async def get_document_status(kb_id: str, doc_id: str):
    return {"id": doc_id, "status": "indexed"}


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


@router.get("/users/{user_id}")
async def get_user(user_id: str):
    return {"id": user_id, "username": "admin", "display_name": "系统管理员"}


@router.get("/users/{user_id}/conversations")
async def list_conversations(user_id: str):
    return {"data": [], "total": 0}


@router.get("/admin/stats")
async def get_system_stats():
    llm_router = get_llm_router()
    health = await llm_router.check_health()
    return {
        "total_kbs": 1,
        "total_documents": 0,
        "total_chunks": 0,
        "total_users": 1,
        "pipeline_type": settings.PIPELINE_TYPE,
        "llm": health,
        "total_fallbacks": llm_router.total_fallbacks,
        "is_fallback_mode": llm_router.is_fallback_mode,
    }


@router.get("/admin/users")
async def list_users():
    return {"data": [{"id": "1", "username": "admin", "role": "admin"}], "total": 1}
