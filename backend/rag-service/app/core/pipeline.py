"""
查询 Pipeline 编排器
抽象所有查询流程，Phase 1 = NaiveRAG, Phase 2 = AgenticRAG
"""
import logging
import time
import uuid
from typing import Any, AsyncGenerator, List, Dict, Optional, Callable

from app.core.protocols import (
    QueryPipeline, PipelineEvent, LLMProvider,
    VectorStore, KeywordStore, EmbeddingModel, Reranker,
    RetrievedChunk, rrf_merge,
)
from app.core.llm_router import LLMRouter
from app.llm.llm_service import LLMService, SYSTEM_PROMPT_TEMPLATE
from app.core.cache import conversation_cache
from app.core.tracing import start_span, set_span_attribute
from app.core.metrics import (
    record_pipeline_step, record_pipeline_chunks,
    record_retrieval, record_llm_call,
)

logger = logging.getLogger(__name__)


class NaiveRAGPipeline(QueryPipeline):
    """
    Naive RAG Pipeline (Phase 1)
    流程: 向量化 → 混合检索 → 重排序 → 上下文构建 → LLM 流式生成

    Phase 2 时，新增 AgenticRAGPipeline 继承 QueryPipeline，
    替换 pipeline_type 配置即可，routes.py 无需修改。
    """

    def __init__(
        self,
        vector_store: VectorStore,
        keyword_store: KeywordStore,
        embedding_model: EmbeddingModel,
        reranker: Reranker,
        llm_router: LLMRouter,
    ):
        self._vector_store = vector_store
        self._keyword_store = keyword_store
        self._embedding_model = embedding_model
        self._reranker = reranker
        self._llm_router = llm_router
        self._hooks: List[Callable] = []
        self._llm_service = LLMService()  # 复用上下文压缩

    @property
    def pipeline_name(self) -> str:
        return "naive-rag"

    def register_hook(self, hook: Callable):
        self._hooks.append(hook)

    async def _emit(self, event: PipelineEvent):
        for hook in self._hooks:
            try:
                await hook(event)
            except Exception as e:
                logger.warning(f"Pipeline hook 异常: {e}")

    async def execute(
        self,
        question: str,
        kb_id: str,
        conversation_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[PipelineEvent, None]:
        """执行完整 RAG 流程 (带链路追踪和 LLM 指标)"""
        conv_id = conversation_id or str(uuid.uuid4())
        history = history or []

        pipeline_start = time.monotonic()

        with start_span("rag.pipeline", {
            "question.length": len(question),
            "kb_id": kb_id,
            "conversation_id": conv_id,
        }):
            # ===== Step 1: 查询向量化 =====
            await self._emit(PipelineEvent("retrieval.started", {"question": question, "kb_id": kb_id}))

            t0 = time.monotonic()
            with start_span("rag.embedding"):
                query_vector = await self._embedding_model.embed_query(question)
            embed_time = (time.monotonic() - t0) * 1000
            record_pipeline_step("embedding", embed_time)
            set_span_attribute("embedding.dimension", len(query_vector))

            await self._emit(PipelineEvent("retrieval.embedded", {"dimension": len(query_vector)}))

            # ===== Step 2a: 向量检索 (纯向量) =====
            t0 = time.monotonic()
            with start_span("rag.vector_search", {"top_k": 30}):
                vector_results = await self._vector_store.similarity_search(
                    collection_name=kb_id,
                    query_vector=query_vector,
                    top_k=30,
                    kb_id=kb_id,
                )
            vector_time = (time.monotonic() - t0) * 1000
            record_pipeline_step("vector_search", vector_time)
            record_retrieval("vector", vector_time)
            set_span_attribute("vector_search.hits", len(vector_results))

            await self._emit(PipelineEvent(
                "retrieval.vector_done",
                {"count": len(vector_results),
                 "top_score": vector_results[0].score if vector_results else 0},
            ))

            # ===== Step 2b: 关键词检索 (独立于向量库) =====
            t0 = time.monotonic()
            with start_span("rag.keyword_search", {"top_k": 30}):
                keyword_results = await self._keyword_store.keyword_search(
                    collection_name=kb_id,
                    query_text=question,
                    top_k=30,
                    kb_id=kb_id,
                )
            keyword_time = (time.monotonic() - t0) * 1000
            record_pipeline_step("keyword_search", keyword_time)
            record_retrieval("keyword", keyword_time)
            set_span_attribute("keyword_search.hits", len(keyword_results))

            await self._emit(PipelineEvent(
                "retrieval.keyword_done",
                {"count": len(keyword_results),
                 "top_score": keyword_results[0].score if keyword_results else 0},
            ))

            # ===== Step 2c: RRF 融合 (纯算法，不依赖数据库) =====
            t0 = time.monotonic()
            retrieved = rrf_merge(vector_results, keyword_results, top_k=30)
            rrf_time = (time.monotonic() - t0) * 1000
            record_pipeline_step("rrf_merge", rrf_time)

            if not retrieved:
                logger.warning(f"检索结果为空: kb_id={kb_id}, question={question[:50]}")

            record_pipeline_chunks("retrieved", len(retrieved))
            set_span_attribute("retrieval.merged_count", len(retrieved))

            await self._emit(PipelineEvent(
                "retrieval.merged",
                {"vector_count": len(vector_results),
                 "keyword_count": len(keyword_results),
                 "merged_count": len(retrieved)},
            ))

            # ===== Step 3: 重排序 =====
            t0 = time.monotonic()
            if retrieved and self._reranker:
                with start_span("rag.rerank"):
                    retrieved = await self._reranker.rerank(question, retrieved, top_k=5)
            else:
                retrieved = retrieved[:5]
            rerank_time = (time.monotonic() - t0) * 1000
            record_pipeline_step("rerank", rerank_time)
            record_retrieval("rerank", rerank_time)
            record_pipeline_chunks("reranked", len(retrieved))

            await self._emit(PipelineEvent(
                "rerank.completed",
                {"count": len(retrieved)},
            ))

            # ===== Step 4: 上下文压缩 (长对话) =====
            compressed_summary = await self._llm_service._compress_history(history)

            # ===== Step 5: 构建 Prompt =====
            context_text = self._build_context_text(retrieved)
            history_text = self._build_history_text(history, compressed_summary)

            system_content = SYSTEM_PROMPT_TEMPLATE.format(
                context=context_text or "无相关文档",
                history=history_text or "无历史对话",
                question=question,
            )

            messages = [{"role": "system", "content": system_content}]

            recent_messages = history[-4:] if len(history) > 4 else history
            for msg in recent_messages:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })
            messages.append({"role": "user", "content": question})

            await self._emit(PipelineEvent(
                "llm.started",
                {"model": self._llm_router.current_model, "history_compressed": bool(compressed_summary)},
            ))

            # ===== Step 6: LLM 流式生成 (带降级和追踪) =====
            full_response = []
            llm_start = time.monotonic()
            first_token_time: Optional[float] = None
            provider_name = getattr(self._llm_router._primary, "_name", "unknown")

            try:
                with start_span("rag.llm.call", {
                    "provider": provider_name,
                    "model": self._llm_router.current_model,
                    "is_fallback": self._llm_router.is_fallback_mode,
                }):
                    async for token in self._llm_router.chat_stream(
                        messages,
                        temperature=0.3,
                        max_tokens=8192,
                    ):
                        if first_token_time is None:
                            first_token_time = time.monotonic()
                            ttf_ms = (first_token_time - llm_start) * 1000
                            set_span_attribute("llm.time_to_first_token_ms", ttf_ms)
                        full_response.append(token)
                        yield PipelineEvent("llm.token", {"content": token})

            except Exception as e:
                error_msg = f"AI 服务异常: {str(e)}"
                logger.error(error_msg)
                yield PipelineEvent("llm.error", {"content": error_msg})
                # 记录失败指标
                record_llm_call(provider_name, self._llm_router.current_model, "error")
                return

            llm_latency = (time.monotonic() - llm_start) * 1000

            response_text = "".join(full_response)
            tokens_count = len(full_response)

            # 记录 LLM 指标
            result = "fallback" if self._llm_router.is_fallback_mode else "success"
            record_llm_call(
                provider=provider_name,
                model=self._llm_router.current_model,
                result=result,
                latency_ms=llm_latency,
                tokens_total=tokens_count,
                tokens_completion=tokens_count,
            )
            set_span_attribute("llm.tokens_generated", tokens_count)
            set_span_attribute("llm.latency_ms", llm_latency)
            if first_token_time:
                record_pipeline_step("llm.first_token", first_token_time - llm_start)

            await self._emit(PipelineEvent("llm.completed", {
                "tokens": tokens_count,
                "total_chars": len(response_text),
                "model": self._llm_router.current_model,
            }))

            # ===== Step 7: 持久化对话历史 =====
            await self._persist_conversation(conv_id, history, question, response_text, retrieved)

            # ===== Step 8: 完成 =====
            total_time = (time.monotonic() - pipeline_start) * 1000
            record_pipeline_step("total", total_time)
            record_pipeline_chunks("final", len(retrieved))

            sources = self._extract_sources(retrieved)
            yield PipelineEvent("pipeline.done", {
                "conversation_id": conv_id,
                "model": self._llm_router.current_model,
                "is_fallback": self._llm_router.is_fallback_mode,
                "sources": sources,
                "total_latency_ms": total_time,
            })

    # ========== 辅助方法 ==========

    def _build_context_text(self, retrieved: List[RetrievedChunk]) -> str:
        """
        构建上下文文本
        每个文档块附带文档 ID 和来源名称，供 LLM 引用
        """
        parts = []
        for i, doc in enumerate(retrieved, 1):
            # 文档标记: AI 通过 [Doc-{id}] 格式引用
            doc_tag = f"Doc-{i}"
            source_name = doc.source_file or f"文档-{doc.document_id[:8] if doc.document_id else i}"
            retrieval_tag = "🔍 向量匹配" if doc.retrieval_type == "vector" else "🔑 关键词匹配"
            header = (
                f"[{doc_tag}] {retrieval_tag} | 来源: {source_name}\n"
                f"  文档ID: {doc.document_id} | 相关度: {doc.rerank_score or doc.score:.4f}"
            )
            parts.append(f"--- {header} ---\n{doc.content}")

        # 在末尾添加引用指南
        if parts:
            parts.append(
                "\n[引用规则] 在回答中引用时请使用 [Doc-N] 格式标注来源，"
                "例如: '系统的端口配置在 config.yaml 中 [Doc-1]'"
            )
        return "\n".join(parts)

    def _build_history_text(
        self, history: List[Dict[str, str]], compressed_summary: str
    ) -> str:
        """构建历史文本"""
        parts = []
        if compressed_summary:
            parts.append(f"[历史摘要] {compressed_summary}")

        recent = history[-4:] if len(history) > 4 else history
        for msg in recent:
            role = "用户" if msg.get("role") == "user" else "AI"
            parts.append(f"{role}: {msg.get('content', '')}")
        return "\n".join(parts)

    def _extract_sources(self, retrieved: List[RetrievedChunk]) -> List[Dict[str, Any]]:
        """提取引用来源 (含完整元数据，供前端渲染)"""
        seen = set()
        sources = []
        for i, doc in enumerate(retrieved):
            key = doc.document_id + doc.content[:50]
            if key in seen:
                continue
            seen.add(key)
            sources.append({
                "doc_index": i + 1,
                "document_id": doc.document_id,
                "content_preview": doc.content[:300],
                "score": round(max(doc.rerank_score, doc.score), 4),
                "source_file": doc.source_file,
                "retrieval_type": doc.retrieval_type,
                "doc_tag": f"Doc-{i + 1}",
                "metadata": doc.metadata,
            })
        return sources

    async def _persist_conversation(
        self,
        conv_id: str,
        history: List[Dict[str, str]],
        question: str,
        answer: str,
        sources: List[RetrievedChunk],
    ):
        """持久化对话到 Redis 缓存"""
        try:
            user_msg = {"role": "user", "content": question}
            assistant_msg = {
                "role": "assistant",
                "content": answer,
                "sources": self._extract_sources(sources),
            }
            await conversation_cache.append_message(conv_id, user_msg)
            await conversation_cache.append_message(conv_id, assistant_msg)
        except Exception as e:
            logger.warning(f"对话持久化失败: {e}")
