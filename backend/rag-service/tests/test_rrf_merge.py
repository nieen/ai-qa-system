"""
RRF (Reciprocal Rank Fusion) 融合算法单元测试

测试覆盖:
  - 两路结果完全不同的场景
  - 两路结果完全重叠的场景
  - 两路结果部分重叠的场景
  - 空结果边界情况
  - top_k 截断
  - RRF 常数 k 的影响
"""
import pytest
from app.core.protocols import RetrievedChunk, rrf_merge


def _chunk(content: str, chunk_id: str, score: float, rtype: str = "vector") -> RetrievedChunk:
    return RetrievedChunk(
        content=content,
        chunk_id=chunk_id,
        score=score,
        retrieval_type=rtype,
    )


class TestRRFMerge:

    def test_no_overlap(self):
        """两路结果完全不同 → 按 RRF 分数交错排列
        
        vector: 文档 A(rank0), 文档 B(rank1)
        keyword: 文档 C(rank0), 文档 D(rank1)
        
        RRF scores (k=60):
          文档 A: 1/61 ≈ 0.01639  (vector rank0)
          文档 B: 1/62 ≈ 0.01613  (vector rank1)
          文档 C: 1/61 ≈ 0.01639  (keyword rank0)
          文档 D: 1/62 ≈ 0.01613  (keyword rank1)
        
        排序: A == C > B == D
        priority from dict insertion order → A, B, C, D → A==C tie → A goes first
        """
        vectors = [
            _chunk("文档 A", "a", 0.95),
            _chunk("文档 B", "b", 0.90),
        ]
        keywords = [
            _chunk("文档 C", "c", 0.85),
            _chunk("文档 D", "d", 0.80),
        ]

        result = rrf_merge(vectors, keywords, k=60, top_k=4)
        assert len(result) == 4
        # 文档 A 和 C 得分相同(1/61), A 先被插入 dict 所以排前面
        assert result[0].chunk_id == "a"
        # 文档 C 得分与 A 相同(1/61), 高于 B(1/62)
        assert result[1].chunk_id == "c"
        assert result[2].chunk_id == "b"
        assert result[3].chunk_id == "d"

    def test_full_overlap(self):
        """两路结果完全一致 → 每条文档获得双倍分数"""
        vectors = [
            _chunk("文档 A", "a", 0.95),
            _chunk("文档 B", "b", 0.90),
        ]
        keywords = [
            _chunk("文档 A", "a", 0.70),
            _chunk("文档 B", "b", 0.65),
        ]

        result = rrf_merge(vectors, keywords, k=60, top_k=2)
        assert len(result) == 2
        # "文档 A" 在两路中 rank 都是 0 → score = 1/61 + 1/61 ≈ 0.0328
        # "文档 B" 在两路中 rank 都是 1 → score = 1/62 + 1/62 ≈ 0.0323
        assert result[0].chunk_id == "a"
        assert result[0].score > result[1].score

    def test_partial_overlap(self):
        """部分重叠 → 重叠文档排名上升"""
        vectors = [
            _chunk("文档 A", "a", 0.95),
            _chunk("文档 B", "b", 0.90),
            _chunk("文档 C", "c", 0.85),
        ]
        keywords = [
            _chunk("文档 A", "a", 0.70),  # 重叠: 0+0
            _chunk("文档 D", "d", 0.65),  # 不重叠
        ]

        result = rrf_merge(vectors, keywords, k=60, top_k=3)
        assert len(result) == 3
        # "文档 A" 两路都命中 → score = 1/61 + 1/61 = 2/61 ≈ 0.0328 → rank 1
        assert result[0].chunk_id == "a"

    def test_empty_vector_results(self):
        """向量检索结果为空 → 仅返回关键词结果"""
        keywords = [
            _chunk("文档 A", "a", 0.80),
            _chunk("文档 B", "b", 0.75),
        ]
        result = rrf_merge([], keywords, top_k=5)
        assert len(result) == 2
        assert result[0].chunk_id == "a"

    def test_empty_keyword_results(self):
        """关键词检索结果为空 → 仅返回向量结果"""
        vectors = [
            _chunk("文档 A", "a", 0.90),
        ]
        result = rrf_merge(vectors, [], top_k=5)
        assert len(result) == 1
        assert result[0].chunk_id == "a"

    def test_both_empty(self):
        """两路结果均为空 → 返回空列表"""
        result = rrf_merge([], [])
        assert result == []

    def test_top_k_truncation(self):
        """top_k 截断 → 只返回 top_k 条"""
        vectors = [_chunk(f"文档 {i}", str(i), 0.9 - i * 0.01) for i in range(10)]
        keywords = [_chunk(f"文档 K{i}", f"k{i}", 0.7 - i * 0.01) for i in range(10)]

        result = rrf_merge(vectors, keywords, top_k=5)
        assert len(result) == 5

    def test_same_content_different_chunk_id(self):
        """不同 chunk_id 但内容相同的文档各自独立计分"""
        vectors = [_chunk("相同内容", "v1", 0.90)]
        keywords = [_chunk("相同内容", "k1", 0.80)]

        result = rrf_merge(vectors, keywords, top_k=2)
        assert len(result) == 2  # chunk_id 不同，视为不同文档
        assert result[0].chunk_id == "v1"

    def test_rrf_score_calculation(self):
        """验证 RRF 分数计算公式正确"""
        vectors = [_chunk("文档", "a", 0.90)]
        # 只一路命中: score = 1/(60 + 0 + 1) = 1/61 ≈ 0.01639
        result = rrf_merge(vectors, [], k=60, top_k=1)
        assert abs(result[0].score - 1.0 / 61.0) < 1e-6
