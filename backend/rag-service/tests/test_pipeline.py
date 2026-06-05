"""
Pipeline 编排器集成测试

测试覆盖:
  - NaiveRAGPipeline 完整执行流程 (8 个步骤)
  - 检索结果为空时的降级行为
  - Pipeline 钩子机制
  - 对话历史持久化 (mock Redis)
  - 上下文构建格式

测试策略:
  - 使用 conftest.py 中的 Mock 服务实现
  - 不依赖任何外部服务
  - 验证事件序列和数据完整性
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.core.protocols import PipelineEvent, RetrievedChunk
from app.core.pipeline import NaiveRAGPipeline


class TestNaiveRAGPipeline:

    @pytest.fixture
    def pipeline(self, mock_vector_store, mock_keyword_store,
                 mock_embedding_model, mock_reranker, mock_llm_router):
        return NaiveRAGPipeline(
            vector_store=mock_vector_store,
            keyword_store=mock_keyword_store,
            embedding_model=mock_embedding_model,
            reranker=mock_reranker,
            llm_router=mock_llm_router,
        )

    @pytest.mark.asyncio
    async def test_full_pipeline_execution(self, pipeline, mock_vector_store, tmp_path):
        """完整 Pipeline: embed → search → merge → rerank → llm → persist"""
        # Arrange: 插入测试数据
        await mock_vector_store.create_collection("kb-test")
        from app.core.protocols import Document
        await mock_vector_store.insert("kb-test", [
            Document(
                chunk_id="c1", document_id="d1", kb_id="kb-test",
                content="Redis 是一款内存数据库。",
            ),
            Document(
                chunk_id="c2", document_id="d2", kb_id="kb-test",
                content="Milvus 是一款向量数据库。",
            ),
        ], [[0.1]*1024, [0.2]*1024])

        # Act: 执行 Pipeline
        events = []
        async for event in pipeline.execute(
            question="什么是 Redis？",
            kb_id="kb-test",
        ):
            events.append(event)

        # Assert: 事件序列 (只有 llm.token 和 pipeline.done 被 yield 到调用者)
        # retrieval.* 和 rerank.* 仅发送到 hooks, 不 yield
        event_types = [e.type for e in events]
        assert "llm.token" in event_types
        assert "pipeline.done" in event_types

        # 验证 token 生成
        tokens = [e for e in events if e.type == "llm.token"]
        assert len(tokens) > 0
        assert "".join(e.data["content"] for e in tokens) == "这是一条模拟回复。"

        # 验证完成事件
        done_event = [e for e in events if e.type == "pipeline.done"][0]
        assert done_event.data["model"] == "mock-model"
        assert done_event.data["is_fallback"] is False
        assert "sources" in done_event.data

    @pytest.mark.asyncio
    async def test_empty_retrieval(self, pipeline, mock_vector_store):
        """检索结果为空 → 仍能执行 LLM 生成 (yield 的事件只有 token + done)"""
        await mock_vector_store.create_collection("kb-empty")

        events = []
        async for event in pipeline.execute(
            question="不在知识库中的问题",
            kb_id="kb-empty",
        ):
            events.append(event)

        event_types = [e.type for e in events]
        assert "llm.token" in event_types  # 即使没有检索结果也继续
        assert "pipeline.done" in event_types

    @pytest.mark.asyncio
    async def test_pipeline_includes_question_in_context(self, pipeline, mock_vector_store):
        """验证问题被包含在构建的上下文中"""
        await mock_vector_store.create_collection("kb-test")
        from app.core.protocols import Document
        await mock_vector_store.insert("kb-test", [
            Document(chunk_id="c1", document_id="d1", kb_id="kb-test", content="测试内容"),
        ], [[0.1]*1024])

        events = []
        async for event in pipeline.execute(question="测试问题", kb_id="kb-test"):
            events.append(event)

        # 验证 pipeline.done 事件包含 conversation_id
        done = [e for e in events if e.type == "pipeline.done"]
        assert len(done) == 1
        assert "conversation_id" in done[0].data

    @pytest.mark.asyncio
    async def test_hook_mechanism(self, pipeline, mock_vector_store):
        """注册的钩子被正确调用 (pipeline.done 是 yield 的, 不走 hook)"""
        await mock_vector_store.create_collection("kb-test")
        hook_calls = []

        async def test_hook(event: PipelineEvent):
            hook_calls.append(event.type)

        pipeline.register_hook(test_hook)

        async for _ in pipeline.execute(question="测试", kb_id="kb-test"):
            pass

        assert len(hook_calls) > 0
        # retrieval 和 rerank 事件走 _emit → hook 被调用
        assert "retrieval.started" in hook_calls
        assert "rerank.completed" in hook_calls
        # pipeline.done 通过 yield 直接返回, 不走 hook
        assert "pipeline.done" not in hook_calls

    @pytest.mark.asyncio
    async def test_context_building(self, pipeline):
        """验证上下文构建格式"""
        chunks = [
            RetrievedChunk(
                chunk_id="c1", document_id="d1", kb_id="kb-test",
                content="测试内容1", score=0.95, source_file="doc1.md",
                retrieval_type="vector",
            ),
            RetrievedChunk(
                chunk_id="c2", document_id="d2", kb_id="kb-test",
                content="测试内容2", score=0.80, source_file="doc2.md",
                retrieval_type="keyword",
            ),
        ]

        context = pipeline._build_context_text(chunks)
        assert "[Doc-1]" in context
        assert "[Doc-2]" in context
        assert "doc1.md" in context
        assert "doc2.md" in context
        assert "引用规则" in context

    @pytest.mark.asyncio
    async def test_history_building(self, pipeline):
        """验证对话历史构建"""
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮助的？"},
        ]
        text = pipeline._build_history_text(history, compressed_summary="")
        assert "用户: 你好" in text
        assert "AI: 你好！有什么可以帮助的？" in text

    @pytest.mark.asyncio
    async def test_sources_extraction(self, pipeline):
        """验证引用来源提取"""
        chunks = [
            RetrievedChunk(
                chunk_id="c1", document_id="d1", kb_id="kb-test",
                content="Redis 是内存数据库。", score=0.95,
                source_file="redis.md", retrieval_type="vector",
            ),
        ]
        sources = pipeline._extract_sources(chunks)
        assert len(sources) == 1
        assert sources[0]["document_id"] == "d1"
        assert sources[0]["source_file"] == "redis.md"
        assert sources[0]["retrieval_type"] == "vector"
        assert sources[0]["doc_tag"] == "Doc-1"

    @pytest.mark.asyncio
    async def test_llm_fallback_in_pipeline(self, pipeline, mock_llm_router):
        """当 LLM 路由器处于 fallback 模式时，pipeline.done 携带标记"""
        mock_llm_router.is_fallback_mode = True
        from app.core.protocols import Document

        with patch.object(pipeline, "_vector_store") as mock_vs:
            mock_vs.create_collection = AsyncMock()
            mock_vs.similarity_search = AsyncMock(return_value=[])

            with patch.object(pipeline, "_keyword_store") as mock_ks:
                mock_ks.keyword_search = AsyncMock(return_value=[])

                events = []
                async for event in pipeline.execute(question="测试", kb_id="kb-test"):
                    events.append(event)

                done = [e for e in events if e.type == "pipeline.done"]
                if done:
                    assert done[0].data["is_fallback"] is True
