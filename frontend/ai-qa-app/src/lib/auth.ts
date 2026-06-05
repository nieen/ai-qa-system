"use client"

/**
 * 认证管理
 *
 * JWT Token 存储在 localStorage，所有 API 请求通过 authHeaders() 注入。
 * Token 由 Go 网关签发（POST /auth/login 返回 { token, user }）。
 * 登出时调用网关 POST /user/logout 将当前 Token 加入 Redis 黑名单，
 * 本地清除 localStorage。
 */

// ==================== Token 管理 ====================

const TOKEN_KEY = "aiqa_auth_token"
const USER_KEY = "aiqa_auth_user"

export interface AuthUser {
  id: string
  username: string
  role: string
  display_name?: string
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function setStoredUser(user: AuthUser): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function isAuthenticated(): boolean {
  return !!getToken()
}

export function isAdmin(): boolean {
  const user = getStoredUser()
  return user?.role === "admin"
}

/**
 * 生成认证 Headers
 * 在已有的 headers 对象上注入 Authorization 头（如果有 token）
 */
export function authHeaders(existing?: Record<string, string>): Record<string, string> {
  const headers = { ...(existing || {}) }
  const token = getToken()
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }
  return headers
}
