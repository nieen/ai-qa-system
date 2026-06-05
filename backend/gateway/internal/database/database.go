package database

import (
	"database/sql"
	"fmt"
	"time"

	_ "github.com/lib/pq"

	"github.com/ai-qa-system/gateway/internal/config"
)

// DB 全局数据库连接
var DB *sql.DB

// Connect 建立 PostgreSQL 连接
func Connect(cfg config.DatabaseConfig) error {
	db, err := sql.Open("postgres", cfg.DSN)
	if err != nil {
		return fmt.Errorf("打开数据库连接失败: %w", err)
	}

	db.SetMaxOpenConns(cfg.MaxOpenConns)
	db.SetMaxIdleConns(cfg.MaxIdleConns)
	db.SetConnMaxLifetime(cfg.ConnMaxLifetime)

	if err := db.Ping(); err != nil {
		db.Close()
		return fmt.Errorf("数据库 Ping 失败: %w", err)
	}

	DB = db
	return nil
}

// Close 关闭数据库连接
func Close() {
	if DB != nil {
		DB.Close()
	}
}

// Ping 检查数据库连接
func Ping() error {
	if DB == nil {
		return fmt.Errorf("数据库未连接")
	}
	return DB.Ping()
}

// UserRow 用户表的一行
type UserRow struct {
	ID           string
	Username     string
	Role         string
	DisplayName  string
	PasswordHash string
	IsActive     bool
	Email        string
	LastLoginAt  *time.Time
	CreatedAt    time.Time
}

// GetUserByUsername 根据用户名查询用户
func GetUserByUsername(username string) (*UserRow, error) {
	row := DB.QueryRow(`
		SELECT id, username, role, display_name, password_hash, is_active, email
		FROM users WHERE username = $1
	`, username)

	u := &UserRow{}
	err := row.Scan(&u.ID, &u.Username, &u.Role, &u.DisplayName, &u.PasswordHash, &u.IsActive, &u.Email)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("查询用户失败: %w", err)
	}
	return u, nil
}

// GetUserByID 根据 ID 查询用户
func GetUserByID(userID string) (*UserRow, error) {
	row := DB.QueryRow(`
		SELECT id, username, role, display_name, password_hash, is_active, email,
		       last_login_at, created_at
		FROM users WHERE id = $1
	`, userID)

	u := &UserRow{}
	err := row.Scan(&u.ID, &u.Username, &u.Role, &u.DisplayName,
		&u.PasswordHash, &u.IsActive, &u.Email, &u.LastLoginAt, &u.CreatedAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("查询用户失败: %w", err)
	}
	return u, nil
}

// CreateUser 创建新用户
func CreateUser(id, username, passwordHash, displayName, email string) error {
	_, err := DB.Exec(`
		INSERT INTO users (id, username, password_hash, display_name, email, role)
		VALUES ($1, $2, $3, $4, $5, 'user')
	`, id, username, passwordHash, displayName, email)
	return err
}

// UpdateLastLogin 更新最后登录时间
func UpdateLastLogin(userID string) error {
	_, err := DB.Exec(`UPDATE users SET last_login_at = NOW() WHERE id = $1`, userID)
	return err
}

// ListUsers 列出所有用户
func ListUsers() ([]UserRow, error) {
	rows, err := DB.Query(`
		SELECT id, username, role, display_name, email, is_active, last_login_at, created_at
		FROM users ORDER BY created_at DESC LIMIT 100
	`)
	if err != nil {
		return nil, fmt.Errorf("查询用户列表失败: %w", err)
	}
	defer rows.Close()

	var users []UserRow
	for rows.Next() {
		var u UserRow
		err := rows.Scan(&u.ID, &u.Username, &u.Role, &u.DisplayName,
			&u.Email, &u.IsActive, &u.LastLoginAt, &u.CreatedAt)
		if err != nil {
			return nil, fmt.Errorf("扫描用户行失败: %w", err)
		}
		users = append(users, u)
	}
	return users, nil
}

// ==================== 合规功能 ====================

// ConsentRecord 用户同意记录
type ConsentRecord struct {
	ID             string
	UserID         string
	ConsentType    string
	ConsentVersion string
	Granted        bool
	GrantedAt      time.Time
}

// RecordConsent 记录用户同意
func RecordConsent(userID, consentType, consentVersion, ipAddress string) error {
	_, err := DB.Exec(`
		INSERT INTO user_consents (user_id, consent_type, consent_version, ip_address)
		VALUES ($1, $2, $3, $4)
	`, userID, consentType, consentVersion, ipAddress)
	return err
}

// ExportUserData 导出用户所有个人数据
type UserExportData struct {
	Profile       UserRow
	Conversations []UserConversation
	Documents     []UserDocument
}

type UserConversation struct {
	ID        string
	Title     string
	CreatedAt time.Time
	Messages  []ConversationMessage
}

type ConversationMessage struct {
	ID        string
	Role      string
	Content   string
	CreatedAt time.Time
}

type UserDocument struct {
	ID        string
	Title     string
	FileType  string
	KbName    string
	CreatedAt time.Time
}

func ExportUserData(userID string) (*UserExportData, error) {
	// 获取用户信息
	user, err := GetUserByID(userID)
	if err != nil {
		return nil, err
	}
	if user == nil {
		return nil, fmt.Errorf("用户不存在")
	}

	data := &UserExportData{
		Profile: *user,
	}

	// 获取对话列表
	convRows, err := DB.Query(`
		SELECT id, title, created_at FROM conversations
		WHERE user_id = $1 ORDER BY created_at DESC
	`, userID)
	if err != nil {
		return nil, fmt.Errorf("查询对话失败: %w", err)
	}
	defer convRows.Close()

	for convRows.Next() {
		var conv UserConversation
		if err := convRows.Scan(&conv.ID, &conv.Title, &conv.CreatedAt); err != nil {
			return nil, fmt.Errorf("扫描对话失败: %w", err)
		}

		// 获取每条对话的消息
		msgRows, err := DB.Query(`
			SELECT id, role, content, created_at FROM messages
			WHERE conversation_id = $1 ORDER BY created_at
		`, conv.ID)
		if err != nil {
			return nil, fmt.Errorf("查询消息失败: %w", err)
		}

		for msgRows.Next() {
			var msg ConversationMessage
			if err := msgRows.Scan(&msg.ID, &msg.Role, &msg.Content, &msg.CreatedAt); err != nil {
				msgRows.Close()
				return nil, fmt.Errorf("扫描消息失败: %w", err)
			}
			conv.Messages = append(conv.Messages, msg)
		}
		msgRows.Close()
		data.Conversations = append(data.Conversations, conv)
	}

	// 获取用户上传的文档
	docRows, err := DB.Query(`
		SELECT d.id, d.title, d.file_type,
		       COALESCE(kb.name, '未知知识库') AS kb_name,
		       d.created_at
		FROM documents d
		LEFT JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id
		WHERE d.created_by = $1
		ORDER BY d.created_at DESC
	`, userID)
	if err == nil {
		defer docRows.Close()
		for docRows.Next() {
			var doc UserDocument
			if err := docRows.Scan(&doc.ID, &doc.Title, &doc.FileType, &doc.KbName, &doc.CreatedAt); err == nil {
				data.Documents = append(data.Documents, doc)
			}
		}
	}

	return data, nil
}

// ==================== 数据删除（PIPL 第47条 — 被遗忘权）====================

// DeleteUserAccount 软删除用户账号（标记 deleted_at）
func DeleteUserAccount(userID string) error {
	_, err := DB.Exec(`
		UPDATE users SET
			is_active = FALSE,
			username = 'deleted_' || SUBSTRING(id::text, 1, 8),
			email = NULL,
			display_name = '已注销用户',
			password_hash = 'DELETED'
		WHERE id = $1
	`, userID)
	return err
}

// CascadeDeleteUserData 级联删除用户所有关联数据（物理删除）
func CascadeDeleteUserData(userID string) error {
	tx, err := DB.Begin()
	if err != nil {
		return fmt.Errorf("开启事务失败: %w", err)
	}
	defer tx.Rollback()

	// 1. 删除消息 (通过 conversation 关联)
	if _, err := tx.Exec(`
		DELETE FROM messages WHERE conversation_id IN
		(SELECT id FROM conversations WHERE user_id = $1)
	`, userID); err != nil {
		return fmt.Errorf("删除消息失败: %w", err)
	}

	// 2. 删除对话
	if _, err := tx.Exec(`DELETE FROM conversations WHERE user_id = $1`, userID); err != nil {
		return fmt.Errorf("删除对话失败: %w", err)
	}

	// 3. 删除用户上传的文档 (逻辑删除，保留知识库结构)
	if _, err := tx.Exec(`
		UPDATE documents SET title = '[已删除]', file_path = NULL
		WHERE created_by = $1
	`, userID); err != nil {
		return fmt.Errorf("删除文档关联失败: %w", err)
	}

	// 4. 删除审计日志
	if _, err := tx.Exec(`DELETE FROM audit_logs WHERE user_id = $1`, userID); err != nil {
		return fmt.Errorf("删除审计日志失败: %w", err)
	}

	// 5. 删除同意记录
	if _, err := tx.Exec(`DELETE FROM user_consents WHERE user_id = $1`, userID); err != nil {
		return fmt.Errorf("删除同意记录失败: %w", err)
	}

	// 6. 删除删除请求
	if _, err := tx.Exec(`DELETE FROM deletion_requests WHERE user_id = $1`, userID); err != nil {
		return fmt.Errorf("删除请求记录失败: %w", err)
	}

	// 7. 删除用户
	if _, err := tx.Exec(`DELETE FROM users WHERE id = $1`, userID); err != nil {
		return fmt.Errorf("删除用户失败: %w", err)
	}

	return tx.Commit()
}

// CreateDeletionRequest 创建删除请求（7天冷静期）
func CreateDeletionRequest(userID string) (string, error) {
	var requestID string
	err := DB.QueryRow(`
		INSERT INTO deletion_requests (user_id, expires_at)
		VALUES ($1, NOW() + INTERVAL '7 days')
		RETURNING id
	`, userID).Scan(&requestID)
	return requestID, err
}

// ConfirmDeletion 确认并执行删除
func ConfirmDeletion(requestID, userID string) error {
	tx, err := DB.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	// 标记请求为已确认
	result, err := tx.Exec(`
		UPDATE deletion_requests SET
			status = 'confirmed',
			confirmed_at = NOW()
		WHERE id = $1 AND user_id = $2 AND status = 'pending'
	`, requestID, userID)
	if err != nil {
		return fmt.Errorf("确认删除请求失败: %w", err)
	}
	affected, _ := result.RowsAffected()
	if affected == 0 {
		return fmt.Errorf("删除请求不存在或已处理")
	}

	tx.Commit()

	// 在事务外执行级联删除（减少锁持有时间）
	return CascadeDeleteUserData(userID)
}

// CancelDeletion 取消删除请求
func CancelDeletion(requestID, userID string) error {
	_, err := DB.Exec(`
		UPDATE deletion_requests SET status = 'cancelled'
		WHERE id = $1 AND user_id = $2 AND status = 'pending'
	`, requestID, userID)
	return err
}

// ==================== 数据保留策略清理 ====================

// CleanupOldConversations 清理超过 retention_days 天未更新的对话
// 返回清理的对话数
func CleanupOldConversations(retentionDays int) (int64, error) {
	result, err := DB.Exec(`
		DELETE FROM conversations
		WHERE updated_at < NOW() - ($1 || ' days')::INTERVAL
	`, fmt.Sprintf("%d", retentionDays))
	if err != nil {
		return 0, fmt.Errorf("清理对话失败: %w", err)
	}
	return result.RowsAffected()
}

// CleanupOldAuditLogs 清理超过 retention_days 天的审计日志
func CleanupOldAuditLogs(retentionDays int) (int64, error) {
	result, err := DB.Exec(`
		DELETE FROM audit_logs
		WHERE created_at < NOW() - ($1 || ' days')::INTERVAL
	`, fmt.Sprintf("%d", retentionDays))
	if err != nil {
		return 0, fmt.Errorf("清理审计日志失败: %w", err)
	}
	return result.RowsAffected()
}

// GetPendingDeletionRequests 获取所有已过期待处理的删除请求
func GetPendingDeletionRequests() ([]string, error) {
	rows, err := DB.Query(`
		SELECT user_id FROM deletion_requests
		WHERE status = 'pending' AND expires_at <= NOW()
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var userIDs []string
	for rows.Next() {
		var uid string
		rows.Scan(&uid)
		userIDs = append(userIDs, uid)
	}
	return userIDs, nil
}

// ==================== 审计日志（统一入口）====================

// AuditLogEntry 写入审计日志（统一入口，带 IP 和 User-Agent）
func AuditLogEntry(userID, action, resourceType, resourceID, ipAddress, userAgent string, details map[string]interface{}) error {
	_, err := DB.Exec(`
		INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details, ip_address, user_agent)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`, userID, action, resourceType, resourceID, details, ipAddress, userAgent)
	return err
}

// AuditLogRow 审计日志行
type AuditLogRow struct {
	ID           string
	UserID       string
	Action       string
	ResourceType string
	ResourceID   string
	Details      interface{}
	IPAddress    string
	UserAgent    string
	CreatedAt    time.Time
}

// QueryAuditLogs 查询审计日志（分页）
func QueryAuditLogs(limit, offset int) ([]AuditLogRow, int, error) {
	var total int
	DB.QueryRow(`SELECT COUNT(*) FROM audit_logs`).Scan(&total)

	rows, err := DB.Query(`
		SELECT id, user_id, action, resource_type, COALESCE(resource_id, ''),
		       COALESCE(ip_address, ''), COALESCE(user_agent, ''), created_at
		FROM audit_logs
		ORDER BY created_at DESC
		LIMIT $1 OFFSET $2
	`, limit, offset)
	if err != nil {
		return nil, 0, fmt.Errorf("查询审计日志失败: %w", err)
	}
	defer rows.Close()

	var logs []AuditLogRow
	for rows.Next() {
		var l AuditLogRow
		if err := rows.Scan(&l.ID, &l.UserID, &l.Action, &l.ResourceType,
			&l.ResourceID, &l.IPAddress, &l.UserAgent, &l.CreatedAt); err != nil {
			return nil, 0, fmt.Errorf("扫描审计日志行失败: %w", err)
		}
		logs = append(logs, l)
	}
	return logs, total, nil
}

// ==================== 系统统计 ====================

type SystemStats struct {
	TotalKBs       int
	TotalDocuments int
	TotalChunks    int64
	TotalUsers     int
}

func GetSystemStats() (*SystemStats, error) {
	stats := &SystemStats{}

	DB.QueryRow(`SELECT COUNT(*) FROM knowledge_bases`).Scan(&stats.TotalKBs)
	DB.QueryRow(`SELECT COUNT(*) FROM documents`).Scan(&stats.TotalDocuments)
	DB.QueryRow(`SELECT COALESCE(SUM(chunk_count), 0) FROM documents`).Scan(&stats.TotalChunks)
	DB.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&stats.TotalUsers)

	return stats, nil
}
