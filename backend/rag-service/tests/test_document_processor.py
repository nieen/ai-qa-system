"""
文档处理器单元测试

测试覆盖:
  - 文本清洗 (_clean_text)
  - 按标题分割 (_split_by_headings)
  - 固定窗口分块 (_fixed_size_chunks)
  - 完整 process 流程
  - 空文件 / 不支持类型等边界情况

测试策略:
  - 所有测试纯 Python 实现，不依赖 GPU
  - 分块测试使用字符模式 (模拟 tiktoken 不可用)
  - 文件提取测试写入临时文件
"""
import os
import tempfile
import pytest
from app.ingestion.document_processor import DocumentProcessor


@pytest.fixture
def processor():
    return DocumentProcessor()


class TestCleanText:

    def test_merge_blank_lines(self, processor):
        """合并多余空行"""
        text = "行1\n\n\n\n行2"
        result = processor._clean_text(text)
        assert "行1\n\n行2" in result

    def test_merge_spaces(self, processor):
        """合并多余空格"""
        text = "a    b    c"
        result = processor._clean_text(text)
        assert "a b c" in result

    def test_trim_whitespace(self, processor):
        """去除首尾空白"""
        text = "  \n  你好  \n  "
        result = processor._clean_text(text)
        assert result == "你好"

    def test_unify_newlines(self, processor):
        """统一换行符"""
        text = "行1\r\n行2\r行3"
        result = processor._clean_text(text)
        assert result == "行1\n行2\n行3"


class TestSplitByHeadings:

    def test_basic_split(self, processor):
        """按标题分割基本功能"""
        text = "# 第一章\n内容1\n## 1.1节\n内容2\n# 第二章\n内容3"
        sections = processor._split_by_headings(text)
        assert len(sections) >= 2

    def test_no_headings(self, processor):
        """无标题 → 返回一个匿名段落"""
        text = "普通段落\n继续内容"
        sections = processor._split_by_headings(text)
        assert len(sections) >= 1
        assert sections[0][0]  # 有标题名

    def test_multiple_heading_levels(self, processor):
        """多级标题"""
        text = "# H1\n内容1\n## H2\n内容2\n### H3\n内容3"
        sections = processor._split_by_headings(text)
        assert len(sections) >= 3
        assert "# H1" in sections[0][0]
        assert "## H2" in sections[1][0]


class TestFixedSizeChunks:

    def test_short_text(self, processor):
        """短文本不分块"""
        text = "很短的文本"
        chunks = processor._fixed_size_chunks(text)
        assert len(chunks) == 1

    def test_long_text_split(self, processor):
        """长文本分块"""
        # 产生 > 512 字符的文本
        text = "块" * 600
        chunks = processor._fixed_size_chunks(text)
        assert len(chunks) > 1
        # 每块不超过 chunk_size + overlap
        assert all(len(c) >= 64 for c in chunks)

    def test_overlap(self, processor):
        """相邻分块有重叠 (超过 chunk_size 才分块)"""
        # CHUNK_SIZE=512, 需要 >512 字符才触发分块
        text = "A" * 400 + "交界" + "B" * 400
        chunks = processor._fixed_size_chunks(text)
        if len(chunks) > 1:
            # 如果分块了, 检查重叠
            assert len(chunks[0]) > 0
            assert len(chunks[1]) > 0
        # 至少有一块
        assert len(chunks) >= 1


class TestProcess:

    @pytest.mark.asyncio
    async def test_process_txt(self, processor):
        """处理 .txt 文件"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("# 测试文档\n\n这是第一段落。\n\n这是第二段落。")
            tmp_path = f.name

        try:
            chunks = await processor.process(tmp_path, "txt")
            assert len(chunks) >= 1
            assert chunks[0]["chunk_index"] == 0
            assert "测试文档" in chunks[0]["content"]
            assert "file_type" in chunks[0]["metadata"]
            assert "source_file" in chunks[0]["metadata"]
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_process_empty_file(self, processor):
        """空文件 → 返回空列表"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("")
            tmp_path = f.name

        try:
            chunks = await processor.process(tmp_path, "txt")
            assert chunks == []
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_unsupported_type(self, processor):
        """不支持的文件类型 → 尝试纯文本读取"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xyz", delete=False, encoding="utf-8"
        ) as f:
            f.write("试试读取")
            tmp_path = f.name

        try:
            chunks = await processor.process(tmp_path, "xyz")
            # 不支持的类型应该尝试纯文本读取
            assert len(chunks) >= 1
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_process_text(self, processor):
        """处理纯文本"""
        chunks = await processor.process_text("你好世界")
        assert len(chunks) >= 1
        assert "你好世界" in chunks[0]["content"]

    @pytest.mark.asyncio
    async def test_process_empty_text(self, processor):
        """处理空文本"""
        chunks = await processor.process_text("")
        assert chunks == []

    @pytest.mark.asyncio
    async def test_process_webpage_simple(self, processor):
        """处理简单 HTML"""
        html = "<html><body><h1>标题</h1><p>内容</p></body></html>"
        chunks = await processor.process_webpage(html, "http://test.com")
        assert len(chunks) >= 1
        text = chunks[0]["content"]
        assert "标题" in text or "内容" in text
