-- Baseline migration — 网关服务初始 schema
-- CREATE DATABASE aiqa_gateway;
-- \c aiqa_gateway
-- 需先启用扩展: CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
--                CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 组织
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 用户
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

-- 审计日志
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id UUID,
    details JSONB DEFAULT '{}',
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 用户同意记录 (PIPL)
CREATE TABLE IF NOT EXISTS user_consents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    consent_type VARCHAR(50) NOT NULL DEFAULT 'privacy_policy',
    consent_version VARCHAR(50) NOT NULL,
    granted BOOLEAN NOT NULL DEFAULT TRUE,
    ip_address VARCHAR(45),
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 删除请求 (7天冷静期)
CREATE TABLE IF NOT EXISTS deletion_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'cancelled', 'completed')),
    reason TEXT,
    confirmed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '7 days')
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_users_organization ON users(organization_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action_time ON audit_logs(action, created_at);
CREATE INDEX IF NOT EXISTS idx_user_consents_user ON user_consents(user_id);
CREATE INDEX IF NOT EXISTS idx_deletion_requests_user ON deletion_requests(user_id);

-- 默认管理员 (密码: admin123)
INSERT INTO users (username, email, password_hash, display_name, role)
VALUES ('admin', 'admin@company.com', crypt('admin123', gen_salt('bf')), '系统管理员', 'admin')
ON CONFLICT (username) DO NOTHING;

-- 审计日志删除保护触发器
CREATE OR REPLACE FUNCTION fn_protect_audit_logs()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '不允许直接删除审计日志，请使用 AuditLogCleanup 函数（保留 180 天）';
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_protect_audit_logs') THEN
        CREATE TRIGGER trg_protect_audit_logs
            BEFORE DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION fn_protect_audit_logs();
    END IF;
END;
$$;
