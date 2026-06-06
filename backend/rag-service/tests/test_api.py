"""
API 路由集成测试

测试覆盖:
  - 健康检查端点
  - 认证（登录/注册）
  - 知识库 CRUD
  - 文档上传 (含参数校验)
  - 流式问答 SSE
  - LLM 状态查询
  - LLM 重置

测试策略:
  - 使用 FastAPI TestClient (httpx.AsyncClient)
  - 所有底层服务 (Milvus/Redis/Embedding/Reranker/LLM/DB) 通过 monkeypatch mock
  - 不依赖任何外部服务
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app():
    """创建测试用 FastAPI 应用 (独立于 main.py)"""
    from app.api.routes import router
    app = FastAPI(title="test")
    app.include_router(router, prefix="/api/v1")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "test"}
    return app


@pytest.fixture
def mock_deps(app):
    """Mock 所有外部依赖"""
    with patch("app.api.routes.get_vector_store") as mock_get_vs, \
         patch("app.api.routes.get_pipeline") as mock_get_pipe, \
         patch("app.api.routes.get_llm_router") as mock_get_llm, \
         patch("app.api.routes.event_bus.publish", new_callable=AsyncMock) as mock_pub, \
         patch("app.api.routes.event_bus.get_doc_status", new_callable=AsyncMock) as mock_status:

        # Vector Store (方法返回 async results)
        mock_vs = MagicMock()
        mock_vs.create_collection = AsyncMock()
        mock_vs.delete_by_document = AsyncMock()
        mock_get_vs.return_value = mock_vs

        # Pipeline (execute 是 async generator)
        mock_pipe = MagicMock()
        mock_get_pipe.return_value = mock_pipe

        # LLM Router
        mock_llm = MagicMock()
        mock_llm.check_health = AsyncMock(return_value={
            "status": "ok", "primary": True, "primary_model": "mock",
        })
        mock_llm.reset = AsyncMock()
        mock_llm.total_fallbacks = 0
        mock_llm.is_fallback_mode = False
        mock_get_llm.return_value = mock_llm

        yield {
            "vector_store": mock_vs,
            "pipeline": mock_pipe,
            "llm_router": mock_llm,
            "event_bus_publish": mock_pub,
            "event_bus_status": mock_status,
        }


@pytest.fixture
def client(app, mock_deps):
    """测试 HTTP 客户端"""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestHealth:

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "test"

    @pytest.mark.asyncio
    async def test_llm_health(self, client, mock_deps):
        resp = await client.get("/api/v1/llm/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["primary"] is True


class TestKnowledgeBases:

    @pytest.mark.asyncio
    async def test_list_knowledge_bases(self, client):
        resp = await client.get("/api/v1/knowledge-bases")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_create_knowledge_base(self, client, mock_deps):
        resp = await client.post("/api/v1/knowledge-bases", json={
            "name": "测试知识库",
            "description": "测试用",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "测试知识库"
        assert data["status"] == "active"
        assert "id" in data
        # 验证 create_collection 被调用
        mock_deps["vector_store"].create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_knowledge_base(self, client):
        resp = await client.get("/api/v1/knowledge-bases/test-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-id"


class TestDocuments:

    @pytest.mark.asyncio
    async def test_upload_document(self, client, mock_deps, tmp_path):
        """上传文档 → 返回 processing + 发布 Redis Stream"""
        content = b"# Test\n\nHello world"
        resp = await client.post(
            "/api/v1/knowledge-bases/kb-test/documents/upload",
            files={"file": ("test.txt", content, "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert "id" in data
        # 验证 event_bus.publish 被调用
        mock_deps["event_bus_publish"].assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_invalid_type(self, client):
        """不支持的文件类型 → 400"""
        resp = await client.post(
            "/api/v1/knowledge-bases/kb-test/documents/upload",
            files={"file": ("test.exe", b"data", "application/octet-stream")},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_empty_filename(self, client):
        """空文件名 → 400 或 422"""
        resp = await client.post(
            "/api/v1/knowledge-bases/kb-test/documents/upload",
            files={"file": ("", b"data", "text/plain")},
        )
        # FastAPI 路由中校验或 Pydantic 校验都可能拦截
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_document_status(self, client, mock_deps):
        """查询文档状态"""
        mock_deps["event_bus_status"].return_value = {
            "doc_id": "doc-1",
            "status": "completed",
            "chunk_count": 5,
        }

        resp = await client.get(
            "/api/v1/knowledge-bases/kb-test/documents/doc-1/status"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_document_status_queued(self, client, mock_deps):
        """状态未查到 → 返回 queued"""
        mock_deps["event_bus_status"].return_value = None

        resp = await client.get(
            "/api/v1/knowledge-bases/kb-test/documents/doc-404/status"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    @pytest.mark.asyncio
    async def test_delete_document(self, client, mock_deps):
        resp = await client.delete(
            "/api/v1/knowledge-bases/kb-test/documents/doc-1"
        )
        assert resp.status_code == 200
        mock_deps["vector_store"].delete_by_document.assert_called_once_with(
            "kb-test", "doc-1"
        )


class TestChat:

    @pytest.mark.asyncio
    async def test_chat_streaming(self, client, mock_deps):
        """SSE 流式问答"""
        # Mock pipeline.execute 模拟流式事件
        from app.core.protocols import PipelineEvent

        async def mock_execute(question, kb_id, conversation_id=None, history=None):
            yield PipelineEvent("retrieval.merged", {
                "vector_count": 3, "keyword_count": 2, "merged_count": 5,
            })
            yield PipelineEvent("llm.token", {"content": "这是"})
            yield PipelineEvent("llm.token", {"content": "测试"})
            yield PipelineEvent("llm.token", {"content": "回复"})
            yield PipelineEvent("pipeline.done", {
                "conversation_id": "conv-1",
                "model": "mock",
                "is_fallback": False,
                "sources": [],
            })

        mock_deps["pipeline"].execute = mock_execute

        resp = await client.post(
            "/api/v1/knowledge-bases/kb-test/chat",
            json={"question": "测试问题"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"

        # 解析 SSE 流
        lines = resp.text.strip().split("\n\n")
        events = []
        for line in lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        # 验证事件序列
        assert events[0]["type"] == "metadata"
        assert events[0]["status"] == "retrieved"
        assert events[-1]["type"] == "done"
        # token 事件
        token_contents = [e["content"] for e in events if e["type"] == "token"]
        assert "".join(token_contents) == "这是测试回复"

    @pytest.mark.asyncio
    async def test_chat_empty_question(self, client, mock_deps):
        """空问题 → 400"""
        resp = await client.post(
            "/api/v1/knowledge-bases/kb-test/chat",
            json={"question": "  "},
        )
        assert resp.status_code == 400


class TestLLM:

    @pytest.mark.asyncio
    async def test_llm_status(self, client, mock_deps):
        resp = await client.get("/api/v1/llm/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_llm_reset(self, client, mock_deps):
        resp = await client.post("/api/v1/llm/reset")
        assert resp.status_code == 200
        mock_deps["llm_router"].reset.assert_called_once()


class TestAdmin:

    @pytest.mark.asyncio
    async def test_admin_audit_logs(self, client):
        """审计日志"""
        resp = await client.get("/api/v1/admin/audit-logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
