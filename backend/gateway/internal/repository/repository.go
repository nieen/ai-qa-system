package repository

import "time"

// User 用户数据行
type User struct {
	ID           string
	Username     string
	PasswordHash string
	DisplayName  string
	Email        string
	Role         string
	IsActive     bool
	CreatedAt    time.Time
}

// UserRepository 用户仓储接口
type UserRepository interface {
	GetByUsername(username string) (*User, error)
	GetByID(userID string) (*User, error)
	Create(id, username, passwordHash, displayName, email string) error
	UpdateLastLogin(userID string) error
	ListUsers() ([]User, error)
}
