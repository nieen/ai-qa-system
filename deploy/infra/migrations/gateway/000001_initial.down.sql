-- 回滚 baseline — 删除所有网关表（逆序删除）
DROP TABLE IF EXISTS deletion_requests CASCADE;
DROP TABLE IF EXISTS user_consents CASCADE;
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS organizations CASCADE;

-- 删除审计触发器
DROP TRIGGER IF EXISTS trg_protect_audit_logs ON audit_logs;
DROP FUNCTION IF EXISTS fn_protect_audit_logs();
