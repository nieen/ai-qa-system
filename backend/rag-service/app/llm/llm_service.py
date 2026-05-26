"""
LLM 调用服务
支持 OpenAI 兼容 API (vLLM)
流式输出 + 上下文构建 + Prompt 模板
"""
import json
import logging
from typing import AsyncGenerator, List, Dict, Any, Optional

from config.settings import settings

logger = logging.getLogger(__name__)

# ==================== 上下文管理常量 ====================

# 对话历史保留策略
# 短对话 (< MAX_VERBATIM_ROUNDS): 所有轮次原样保留
# 长对话 (>= MAX_VERBATIM_ROUNDS): 旧轮次压缩为摘要 + 最近 KEEP_RECENT_ROUNDS 轮原样保留
MAX_VERBATIM_ROUNDS = 6      # 超过此轮数触发压缩
KEEP_RECENT_ROUNDS = 2       # 触发压缩后，最近 N 轮原样保留
HISTORY_SUMMARY_PROMPT = """请将以下对话中已经解决的问题和关键信息总结为一段话（50-100字），只包含事实性信息，不包含客套话。

目标是：后续 AI 能够基于此摘要理解对话背景，无需再阅读完整的原始对话。

对话内容：
{history_text}

摘要："""

# ==================== Prompt 模板 ====================

SYSTEM_PROMPT_TEMPLATE = """你是一个专业的企业知识库 AI 助手。你的职责是基于提供的知识库内容回答用户问题。

## 核心原则
1. **基于知识库回答**: 严格依据提供的参考文档内容回答，不要编造信息。
2. **强制性引用来源**: 每个关键观点、数据、结论都必须在末尾标注来源。
   引用格式: **[来源: 文档名称]**
   如果多个来源支持同一观点，全部列出: **[来源: 文档A][来源: 文档B]**
3. **引用可验证**: 每条引用必须能对应到知识库内容中的具体文档编号，
   不能笼统地说"根据文档"或"根据资料"。
4. **不确定性处理**: 
   - 如果知识库中有相关信息，给出明确回答并引用来源。
   - 如果知识库中信息不足以回答，明确告知 "根据现有知识库无法完全回答这个问题"，然后提供已有的相关信息。
   - 如果知识库中完全没有相关信息，坦诚告知 "知识库中未找到相关信息"。
5. **格式清晰**: 
   - 使用 Markdown 格式组织回答
   - 复杂内容使用标题、列表、表格等结构化呈现
   - 技术术语首次出现时给出简要解释

## 知识库内容
以下是与用户问题相关的知识库内容，请基于此回答：

{context}

## 对话历史
{history}

## 当前问题
{question}

请用中文回答。"""


class LLMService:
    """LLM 调用服务"""

    _instance = None

    def __new__(cls) -> "LLMService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def chat_stream(
        self,
        question: str,
        context: List[Dict[str, Any]],
        history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式问答
        Args:
            question: 用户问题
            context: 检索到的文档上下文
            history: 对话历史
            system_prompt: 自定义系统提示 (不传则使用默认模板)
        Yields:
            SSE 格式的数据块
        """
        # 0. 上下文压缩: 长对话时压缩旧轮次
        compressed_summary = await self._compress_history(history or [])

        # 1. 构建 Prompt
        messages = self._build_messages(
            question, context, history, system_prompt, compressed_summary
        )

        # 2. 调用 LLM API (通过 Router: 支持降级/熔断/超时)
        from app.core.container import container as _svc
        llm_router = _svc.get_llm_router()
        try:
            async for token in llm_router.chat_stream(
                messages, temperature=settings.LLM_TEMPERATURE, max_tokens=settings.LLM_MAX_TOKENS
            ):
                yield self._format_sse(json.dumps({
                    "type": "token",
                    "content": token,
                }))

        except Exception as e:
            logger.error(f"LLM 调用异常: {e}")
            yield self._format_sse(json.dumps({
                "type": "error",
                "content": f"AI 服务异常: {str(e)}",
            }))

    async def chat(
        self,
        question: str,
        context: List[Dict[str, Any]],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        非流式问答
        Returns:
            完整回答文本
        """
        compressed_summary = await self._compress_history(history or [])
        messages = self._build_messages(
            question, context, history, compressed_summary=compressed_summary
        )

        try:
            from app.core.container import container as _svc
            llm_router = _svc.get_llm_router()
            resp = await llm_router.chat(
                messages, temperature=settings.LLM_TEMPERATURE, max_tokens=settings.LLM_MAX_TOKENS
            )
            return resp.content

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return "抱歉，AI 服务暂时不可用，请稍后重试。"

    async def _compress_history(self, history: List[Dict[str, str]]) -> str:
        """
        对超过阈值的对话历史进行摘要压缩
        使用 LLM 将旧轮次压缩为一段摘要，保留关键事实

        策略:
          - ≤ MAX_VERBATIM_ROUNDS 轮: 不压缩，返回空字符串
          - > MAX_VERBATIM_ROUNDS 轮:
              旧轮次 → LLM 摘要
              最近 KEEP_RECENT_ROUNDS 轮 → 原样保留（由调用方处理）

        Args:
            history: 完整对话历史

        Returns:
            压缩后的摘要文本 (或空字符串)
        """
        if not history or len(history) <= MAX_VERBATIM_ROUNDS * 2:
            return ""

        # 用历史信息轮次来算：history 中每 2 条 (user+assistant) = 1 轮对话
        # 但我们直接按条目数算，简单点：超过 MAX_VERBATIM_ROUNDS 个条目就压缩
        # 需要压缩的旧条目 = 全部 - 保留的最新条目
        keep_count = KEEP_RECENT_ROUNDS * 2
        old_history = history[:-keep_count]

        # 构建旧对话文本
        history_text = ""
        for msg in old_history:
            role = "用户" if msg.get("role") == "user" else "AI"
            history_text += f"{role}: {msg.get('content', '')}\n"

        # 限制摘要输入长度，避免摘要本身消耗过多 token
        if len(history_text) > 2000:
            history_text = history_text[-2000:]

        try:
            summary = await self.chat(
                question=HISTORY_SUMMARY_PROMPT.format(history_text=history_text),
                context=[],
                history=[],
            )
            summary = summary.strip()
            logger.info(
                f"对话历史压缩完成: "
                f"{len(old_history)//2} 轮 → 摘要({len(summary)}字)"
            )
            return summary
        except Exception as e:
            logger.warning(f"对话历史摘要生成失败，回退到截断策略: {e}")
            return ""

    def _build_messages(
        self,
        question: str,
        context: List[Dict[str, Any]],
        history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        compressed_summary: str = "",
    ) -> List[Dict[str, str]]:
        """
        构建消息列表

        上下文管理策略:
          1. 长对话时，旧轮次被压缩为一段历史摘要（由 _compress_history 生成）
          2. 历史摘要注入 System Prompt 中
          3. 最近 KEEP_RECENT_ROUNDS 轮作为 messages 保留，
             让 LLM 能直接看到最近的对话上下文
          4. 短对话不压缩，所有轮次原样传递
        """
        # 构建上下文文本
        context_text = ""
        for i, doc in enumerate(context, 1):
            source = ""
            if doc.get("metadata"):
                try:
                    meta = json.loads(doc["metadata"]) if isinstance(doc["metadata"], str) else doc["metadata"]
                    source = f"[来源: {meta.get('source_file', '文档 ' + str(i))}]"
                except (json.JSONDecodeError, TypeError):
                    source = f"[来源: 文档 {i}]"

            context_text += f"\n--- 文档 {i} {source} ---\n{doc.get('content', '')}\n"

        # 构建历史文本 (System Prompt 部分)
        recent_messages = []
        history_text = ""

        if history:
            if compressed_summary:
                # 有摘要：摘要 + 最近 N 轮原样
                keep_count = KEEP_RECENT_ROUNDS * 2
                recent = history[-keep_count:] if len(history) > keep_count else history
                history_text = f"[历史摘要] {compressed_summary}\n"
                for msg in recent:
                    role = "用户" if msg.get("role") == "user" else "AI"
                    history_text += f"{role}: {msg.get('content', '')}\n"
                recent_messages = recent
                logger.debug(
                    f"使用压缩上下文: 摘要({len(compressed_summary)}字) + "
                    f"{len(recent)//2}轮原样"
                )
            else:
                # 无摘要：取最近 MAX_VERBATIM_ROUNDS 条
                keep_count = MAX_VERBATIM_ROUNDS
                recent = history[-keep_count:] if len(history) > keep_count else history
                for msg in recent:
                    role = "用户" if msg.get("role") == "user" else "AI"
                    history_text += f"{role}: {msg.get('content', '')}\n"
                recent_messages = recent

        # 组装 System Prompt
        if system_prompt:
            system_content = system_prompt
        else:
            system_content = SYSTEM_PROMPT_TEMPLATE.format(
                context=context_text,
                history=history_text or "无历史对话",
                question=question,
            )

        messages = [{"role": "system", "content": system_content}]

        # 添加历史消息 (原样传递给 LLM，让模型看到最近的对话语气)
        for msg in recent_messages:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

        # 添加当前问题
        messages.append({"role": "user", "content": question})

        return messages

    def _format_sse(self, data: str) -> str:
        """格式化 SSE 消息"""
        return f"data: {data}\n\n"

    def _extract_sources(self, context: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """提取引用来源"""
        sources = []
        seen = set()

        for doc in context:
            source_key = doc.get("document_id", "") + doc.get("content", "")[:50]
            if source_key in seen:
                continue
            seen.add(source_key)

            source = {
                "document_id": doc.get("document_id", ""),
                "content_preview": doc.get("content", "")[:200],
                "score": round(doc.get("rerank_score", doc.get("score", 0)), 4),
            }

            # 提取文件来源
            if doc.get("metadata"):
                try:
                    meta = json.loads(doc["metadata"]) if isinstance(doc["metadata"], str) else doc["metadata"]
                    source["source_file"] = meta.get("source_file", "")
                except (json.JSONDecodeError, TypeError):
                    pass

            sources.append(source)

        return sources


# 全局单例
llm_service = LLMService()
