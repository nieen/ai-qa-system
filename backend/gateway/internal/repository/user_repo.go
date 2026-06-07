package repository

import (
	"github.com/ai-qa-system/gateway/internal/database"
)

type userRepository struct{}

func NewUserRepository() UserRepository {
	return &userRepository{}
}

func (r *userRepository) GetByUsername(username string) (*User, error) {
	row, err := database.GetUserByUsername(username)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, nil
	}
	return userFromDBRow(row), nil
}

func (r *userRepository) GetByID(userID string) (*User, error) {
	row, err := database.GetUserByID(userID)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, nil
	}
	return userFromDBRow(row), nil
}

func (r *userRepository) Create(id, username, passwordHash, displayName, email string) error {
	return database.CreateUser(id, username, passwordHash, displayName, email)
}

func (r *userRepository) UpdateLastLogin(userID string) error {
	return database.UpdateLastLogin(userID)
}

func (r *userRepository) ListUsers() ([]User, error) {
	rows, err := database.ListUsers()
	if err != nil {
		return nil, err
	}
	users := make([]User, len(rows))
	for i, row := range rows {
		users[i] = *userFromDBRow(&row)
	}
	return users, nil
}

func userFromDBRow(row *database.UserRow) *User {
	return &User{
		ID:           row.ID,
		Username:     row.Username,
		PasswordHash: row.PasswordHash,
		DisplayName:  row.DisplayName,
		Email:        row.Email,
		Role:         row.Role,
		IsActive:     row.IsActive,
		CreatedAt:    row.CreatedAt,
	}
}
