-- ============================================
-- 企业级 AI 智能问答系统 - 数据库初始化脚本
-- ============================================

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================
-- 用户与组织
-- ============================================
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    avatar_url TEXT,
    role VARCHAR(50) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'editor', 'user', 'viewer')),
    organization_id UUID REFERENCES organizations(id),
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 知识库
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    icon VARCHAR(50) DEFAULT '📚',
    owner_id UUID NOT NULL REFERENCES users(id),
    organization_id UUID REFERENCES organizations(id),
    access_level VARCHAR(20) DEFAULT 'private' CHECK (access_level IN ('private', 'team', 'organization', 'public')),
    embedding_model VARCHAR(100) DEFAULT 'BAAI/bge-m3',
    chunk_size INT DEFAULT 512,
    chunk_overlap INT DEFAULT 64,
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'archived')),
    document_count INT DEFAULT 0,
    total_chunks INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 文档
-- ============================================
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    file_type VARCHAR(50) NOT NULL,  -- pdf, docx, md, html, txt, etc.
    file_size BIGINT DEFAULT 0,
    file_path TEXT,                     -- MinIO 存储路径
    source_url TEXT,                    -- 网页来源 URL
    source_type VARCHAR(50) NOT NULL DEFAULT 'upload' CHECK (source_type IN ('upload', 'webpage', 'api', 'git')),
    author VARCHAR(255),
    page_count INT DEFAULT 0,
    chunk_count INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'indexed', 'failed')),
    error_message TEXT,
    checksum VARCHAR(64),               -- 文件哈希，用于变更检测
    metadata JSONB DEFAULT '{}',
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 文档块 (Chunk 元数据)
-- ============================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    content_hash VARCHAR(64),           -- 用于去重
    token_count INT DEFAULT 0,
    chunk_metadata JSONB DEFAULT '{}',  -- 层级路径、标题等
    milvus_id VARCHAR(255),             -- Milvus 中对应向量的 ID
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 对话历史
-- ============================================
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    knowledge_base_id UUID REFERENCES knowledge_bases(id),
    title VARCHAR(500),
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    message_count INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    sources JSONB DEFAULT '[]',         -- 引用的文档块
    tokens_used INT DEFAULT 0,
    latency_ms INT DEFAULT 0,
    feedback_score INT CHECK (feedback_score >= 1 AND feedback_score <= 5),
    feedback_comment TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 审计日志
-- ============================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,        -- login, query, upload, delete, etc.
    resource_type VARCHAR(50),           -- knowledge_base, document, conversation
    resource_id UUID,
    details JSONB DEFAULT '{}',
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- 索引
-- ============================================
CREATE INDEX idx_users_organization ON users(organization_id);
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_knowledge_bases_owner ON knowledge_bases(owner_id);
CREATE INDEX idx_documents_kb ON documents(knowledge_base_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_document_chunks_doc ON document_chunks(document_id);
CREATE INDEX idx_conversations_user ON conversations(user_id);
CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_created_at ON messages(created_at);
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX idx_audit_logs_action_time ON audit_logs(action, created_at);
CREATE INDEX idx_conversations_updated_at ON conversations(updated_at);

-- ============================================
-- 用户同意记录 (合规)
-- ============================================
CREATE TABLE IF NOT EXISTS user_consents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    consent_type VARCHAR(50) NOT NULL DEFAULT 'privacy_policy',  -- privacy_policy, terms_of_service
    consent_version VARCHAR(50) NOT NULL,
    granted BOOLEAN NOT NULL DEFAULT TRUE,
    ip_address VARCHAR(45),
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX idx_user_consents_user ON user_consents(user_id);

-- ============================================
-- 用户删除请求 (7天冷静期)
-- ============================================
CREATE TABLE IF NOT EXISTS deletion_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'cancelled', 'completed')),
    reason TEXT,
    confirmed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '7 days')
);
CREATE INDEX idx_deletion_requests_user ON deletion_requests(user_id);

-- ============================================
-- 默认管理员用户
-- ============================================
-- 密码: admin123 (使用 pgcrypto 加密)
INSERT INTO users (username, email, password_hash, display_name, role)
VALUES ('admin', 'admin@company.com', crypt('admin123', gen_salt('bf')), '系统管理员', 'admin')
ON CONFLICT (username) DO NOTHING;
