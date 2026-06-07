-- ============================================
-- 企业级 AI 智能问答系统 - 数据库初始化脚本
--
-- 职责变更：仅创建数据库和扩展，不创建表。
-- 表的创建由 Alembic migration 管理：
--   aiqa_gateway → deploy/infra/migrations/gateway/
--   aiqa_rag     → deploy/infra/migrations/rag/
-- ============================================

-- 启用 UUID 扩展（在默认库中启用，子库会在各自 \c 后启用）
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================
-- 创建独立数据库
-- ============================================
-- 若使用独立 pg 实例，需在各实例上分别运行对应的 migration。
-- 同一实例时在此处创建子库:
CREATE DATABASE aiqa_gateway;
CREATE DATABASE aiqa_rag;

-- ============================================
-- aiqa_gateway — 仅启用扩展，表由 migration 创建
-- ============================================
\c aiqa_gateway

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================
-- aiqa_rag — 仅启用扩展，表由 migration 创建
-- ============================================
\c aiqa_rag

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
