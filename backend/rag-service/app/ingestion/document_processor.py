"""
文档处理管道
支持 PDF、Word、Markdown、HTML、纯文本等多种格式
"""
import logging
import hashlib
import os
from typing import List, Dict, Any

from config.settings import settings

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """文档处理器 - 解析、清洗、分块"""

    async def process(
        self, file_path: str, file_type: str
    ) -> List[Dict[str, Any]]:
        """
        处理单个文档
        Args:
            file_path: 文件路径
            file_type: 文件类型 (pdf, docx, md, html, txt)
        Returns:
            文档块列表
        """
        # 1. 读取原始内容
        raw_text = await self._extract_text(file_path, file_type)

        if not raw_text.strip():
            logger.warning(f"文档内容为空: {file_path}")
            return []

        # 2. 文本清洗
        clean_text = self._clean_text(raw_text)

        # 3. 分块
        chunks = self._chunk_text(clean_text)

        # 4. 计算哈希
        file_hash = self._compute_hash(file_path)

        logger.info(
            f"文档处理完成: {os.path.basename(file_path)}, "
            f"原始长度: {len(raw_text)}, "
            f"分块数: {len(chunks)}"
        )

        return [
            {
                "content": chunk,
                "chunk_index": idx,
                "metadata": {
                    "source_file": os.path.basename(file_path),
                    "file_type": file_type,
                    "file_hash": file_hash,
                },
            }
            for idx, chunk in enumerate(chunks)
        ]

    async def process_text(
        self, text: str, source: str = "manual"
    ) -> List[Dict[str, Any]]:
        """处理纯文本"""
        if not text.strip():
            return []

        clean_text = self._clean_text(text)
        chunks = self._chunk_text(clean_text)

        return [
            {
                "content": chunk,
                "chunk_index": idx,
                "metadata": {
                    "source": source,
                },
            }
            for idx, chunk in enumerate(chunks)
        ]

    async def process_webpage(self, html_content: str, url: str) -> List[Dict[str, Any]]:
        """处理网页内容"""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html_content, "lxml")
            # 移除脚本和样式
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        except ImportError:
            logger.warning("BeautifulSoup 未安装，使用原始 HTML 提取")
            text = html_content

        return await self.process_text(text, source=url)

    async def _extract_text(self, file_path: str, file_type: str) -> str:
        """从文件提取文本"""
        file_type = file_type.lower()

        try:
            if file_type == "pdf":
                return await self._extract_pdf(file_path)
            elif file_type in ("docx", "doc"):
                return await self._extract_docx(file_path)
            elif file_type == "md":
                return self._read_file(file_path)
            elif file_type in ("html", "htm"):
                return await self._extract_html(file_path)
            elif file_type == "txt":
                return self._read_file(file_path)
            else:
                logger.warning(f"不支持的文件类型: {file_type}，尝试纯文本读取")
                return self._read_file(file_path)
        except Exception as e:
            logger.error(f"文档提取失败 [{file_path}]: {e}")
            return ""

    async def _extract_pdf(self, file_path: str) -> str:
        """提取 PDF 文本"""
        try:
            from unstructured.partition.pdf import partition_pdf

            elements = partition_pdf(file_path, strategy="auto")
            return "\n".join([str(el) for el in elements])
        except ImportError:
            # 降级: 使用 PyMuPDF
            try:
                import fitz

                doc = fitz.open(file_path)
                text_parts = []
                for page in doc:
                    text_parts.append(page.get_text())
                doc.close()
                return "\n".join(text_parts)
            except ImportError:
                logger.warning("PDF 解析库未安装")
                return ""

    async def _extract_docx(self, file_path: str) -> str:
        """提取 Word 文本"""
        try:
            from unstructured.partition.docx import partition_docx

            elements = partition_docx(file_path)
            return "\n".join([str(el) for el in elements])
        except ImportError:
            # 降级: 使用 python-docx
            try:
                import docx

                doc = docx.Document(file_path)
                return "\n".join([p.text for p in doc.paragraphs])
            except ImportError:
                logger.warning("DOCX 解析库未安装")
                return ""

    async def _extract_html(self, file_path: str) -> str:
        """提取 HTML 文本"""
        content = self._read_file(file_path)
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content, "lxml")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)
        except ImportError:
            return content

    def _read_file(self, file_path: str) -> str:
        """读取文件内容"""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _clean_text(self, text: str) -> str:
        """文本清洗"""
        import re

        # 合并多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 合并多余空格
        text = re.sub(r" {3,}", " ", text)
        # 去除空白字符
        text = text.strip()
        # 统一换行符
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        return text

    def _chunk_text(self, text: str) -> List[str]:
        """
        智能分块策略:
        1. 优先按 Markdown 标题分割 (结构化文档)
        2. 固定窗口 + 重叠 (非结构化文档)
        3. 小段落合并
        """
        chunks = []

        # 尝试按标题分割
        sections = self._split_by_headings(text)

        if len(sections) > 1:
            # 结构化文档: 按标题分块
            for heading, content in sections:
                sub_chunks = self._fixed_size_chunks(content)
                chunks.extend(sub_chunks)
        else:
            # 非结构化文档: 固定窗口
            chunks = self._fixed_size_chunks(text)

        # 过滤空块
        chunks = [c.strip() for c in chunks if c.strip()]

        return chunks

    def _split_by_headings(self, text: str):
        """按 Markdown 标题分割"""
        import re

        # 匹配 Markdown 标题
        pattern = r"^(#{1,6})\s+(.+)$"
        lines = text.split("\n")
        sections = []
        current_heading = "前言"
        current_content = []

        for line in lines:
            match = re.match(pattern, line.strip())
            if match:
                if current_content:
                    sections.append((current_heading, "\n".join(current_content)))
                current_heading = line.strip()
                current_content = []
            else:
                current_content.append(line)

        if current_content:
            sections.append((current_heading, "\n".join(current_content)))

        return sections

    def _fixed_size_chunks(self, text: str) -> List[str]:
        """固定窗口分块 (带重叠)"""
        import tiktoken

        # 尝试用 tiktoken 计算 token
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            tokens = enc.encode(text)
        except ImportError:
            # 降级: 按字符估算 (中文字符 ≈ 2 tokens)
            tokens = list(text)

        chunk_size = settings.CHUNK_SIZE
        overlap = settings.CHUNK_OVERLAP
        chunks = []

        if len(tokens) <= chunk_size:
            if isinstance(tokens[0], str) if tokens else False:
                return [text]
            return [enc.decode(tokens)] if not isinstance(tokens[0], str) else [text]

        start = 0
        while start < len(tokens):
            end = min(start + chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]

            if isinstance(chunk_tokens[0], str) if chunk_tokens else False:
                chunk_text = "".join(chunk_tokens)
            else:
                try:
                    chunk_text = enc.decode(chunk_tokens)
                except Exception as e:
                    logger.debug(f"Token decode 失败，回退到字符截断: {e}")
                    chunk_text = text[start:end]

            chunks.append(chunk_text)
            start += chunk_size - overlap

        return chunks

    def _compute_hash(self, file_path: str) -> str:
        """计算文件哈希"""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()


# 全局单例
document_processor = DocumentProcessor()
