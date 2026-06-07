"""Baseline migration — RAG 服务初始 schema

对应的原始建表 SQL: deploy/infra/postgres-init.sql (aiqa_rag 部分)

CREATE DATABASE aiqa_rag;
\c aiqa_rag
(以下表在此迁移中创建)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "2026_01_01_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 RAG 服务所有初始表"""
    
    # UUID 扩展
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # 知识库
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(50), server_default="📚"),
        sa.Column("owner_id", sa.String(64), nullable=False, comment="user UUID, no FK"),
        sa.Column("organization_id", sa.String(64), nullable=True),
        sa.Column("access_level", sa.String(20), server_default="private"),
        sa.Column("embedding_model", sa.String(100), server_default="BAAI/bge-m3"),
        sa.Column("chunk_size", sa.Integer(), server_default="512"),
        sa.Column("chunk_overlap", sa.Integer(), server_default="64"),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("document_count", sa.Integer(), server_default="0"),
        sa.Column("total_chunks", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 文档
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("knowledge_base_id", sa.UUID(), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=False),
        sa.Column("file_size", sa.BigInteger(), server_default="0"),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(50), server_default="upload"),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("page_count", sa.Integer(), server_default="0"),
        sa.Column("chunk_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("metadata_", sa.JSON(), server_default="{}"),
        sa.Column("created_by", sa.String(64), nullable=True, comment="user UUID, no FK"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 文档块
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("document_id", sa.UUID(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("token_count", sa.Integer(), server_default="0"),
        sa.Column("chunk_metadata", sa.JSON(), server_default="{}"),
        sa.Column("milvus_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 对话
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, comment="user UUID, no FK"),
        sa.Column("knowledge_base_id", sa.UUID(), sa.ForeignKey("knowledge_bases.id"), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("message_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 消息
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("conversation_id", sa.UUID(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), server_default="[]"),
        sa.Column("tokens_used", sa.Integer(), server_default="0"),
        sa.Column("latency_ms", sa.Integer(), server_default="0"),
        sa.Column("feedback_score", sa.Integer(), nullable=True),
        sa.Column("feedback_comment", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 索引
    op.create_index("idx_knowledge_bases_owner", "knowledge_bases", ["owner_id"])
    op.create_index("idx_documents_kb", "documents", ["knowledge_base_id"])
    op.create_index("idx_documents_status", "documents", ["status"])
    op.create_index("idx_document_chunks_doc", "document_chunks", ["document_id"])
    op.create_index("idx_conversations_user", "conversations", ["user_id"])
    op.create_index("idx_messages_conversation", "messages", ["conversation_id"])
    op.create_index("idx_messages_created_at", "messages", ["created_at"])
    op.create_index("idx_conversations_updated_at", "conversations", ["updated_at"])


def downgrade() -> None:
    """回滚 baseline — 删除所有 RAG 表"""
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
