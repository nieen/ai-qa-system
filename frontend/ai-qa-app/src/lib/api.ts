"use client"

/**
 * API 客户端
 *
 * 与 Go API 网关通信（网关负责认证/限流/熔断，RAG 服务负责知识库能力）。
 *
 * 认证流程:
 *   1. POST /auth/login → 获取 JWT Token
 *   2. 所有后续请求带上 Authorization: Bearer <token>
 *   3. 收到 401 时清除 Token 并提示重新登录
 *
 * 后端架构:
 *   网关 (8080) → RAG 服务 (8001) → Milvus + PG + Redis
 */

import { getToken, clearToken, authHeaders } from "./auth"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080/api/v1"

// ==================== 类型定义 ====================

interface ChatOptions {
  kbId: string
  question: string
  conversationId?: string
  history?: { role: string; content: string }[]
  onToken: (token: string) => void
  onMetadata: (meta: any) => void
  onSources: (sources: any[]) => void
  onError: (error: string) => void
  onDone: () => void
}

export interface DocumentUploadResult {
  id: string
  title: string
  file_type: string
  status: string
  message: string
}

export interface DocumentStatus {
  id: string
  status: "queued" | "processing" | "completed" | "failed"
  message?: string
  chunk_count?: number
}

export interface LoginResult {
  token: string
  user: {
    id: string
    username: string
    role: string
    display_name?: string
  }
}

export interface RegisterResult {
  message: string
  user: {
    id: string
    username: string
  }
}

export interface UserProfile {
  id: string
  username: string
  display_name: string
  email: string
  role: string
  avatar_url: string
  last_login_at: string
  created_at: string
}

export interface SystemStats {
  total_kbs: number
  total_documents: number
  total_chunks: number
  total_users: number
  pipeline_type: string
  llm: {
    status: string
    primary: boolean
  }
  total_fallbacks: number
  is_fallback_mode: boolean
}

// ==================== 通用请求辅助 ====================

/**
 * 发起带认证的 fetch 请求
 * 自动处理 401 → 清除 Token
 */
async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const resp = await fetch(url, {
    ...options,
    headers: {
      ...authHeaders(options.headers as Record<string, string>),
    },
  })

  if (resp.status === 401) {
    clearToken()
    // 抛出一个特殊错误，前端可据此跳转到登录页
    throw new AuthError("登录已过期，请重新登录")
  }

  return resp
}

/** 认证错误类 */
export class AuthError extends Error {
  constructor(msg: string) {
    super(msg)
    this.name = "AuthError"
  }
}

// ==================== 认证 ====================

/** 用户登录 — 返回 JWT Token */
export async function login(username: string, password: string): Promise<LoginResult> {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw new Error(body.error || body.detail || `登录失败 (${resp.status})`)
  }

  return resp.json()
}

/** 用户注册 — 需同意隐私政策 */
export async function register(
  username: string,
  password: string,
  options?: { display_name?: string; email?: string }
): Promise<RegisterResult> {
  const resp = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      password,
      display_name: options?.display_name || "",
      email: options?.email || "",
      accepted_privacy_policy: true,
    }),
  })

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw new Error(body.error || `注册失败 (${resp.status})`)
  }

  return resp.json()
}

/** 用户登出 — 将当前 Token 加入黑名单 */
export async function logout(): Promise<void> {
  const token = getToken()
  if (!token) return

  try {
    await authFetch(`${API_BASE}/user/logout`, { method: "POST" })
  } catch {
    // 即使登出请求失败，也清除本地 Token
  } finally {
    clearToken()
  }
}

// ==================== 用户管理 ====================

/** 获取当前用户信息 */
export async function getProfile(): Promise<UserProfile> {
  const resp = await authFetch(`${API_BASE}/user/profile`)
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw new Error(body.error || `获取用户信息失败 (${resp.status})`)
  }
  return resp.json()
}

/** 导出个人数据 (PIPL §45) */
export async function exportUserData(): Promise<any> {
  const resp = await authFetch(`${API_BASE}/user/export`)
  if (!resp.ok) throw new Error("导出失败")
  return resp.json()
}

/** 请求删除账号 (PIPL §47), 返回 request_id */
export async function requestAccountDeletion(): Promise<string> {
  const resp = await authFetch(`${API_BASE}/user/delete-request`, { method: "POST" })
  if (!resp.ok) throw new Error("删除请求提交失败")
  const data = await resp.json()
  return data.request_id
}

/** 确认删除账号 */
export async function confirmAccountDeletion(requestId: string): Promise<void> {
  const resp = await authFetch(`${API_BASE}/user/delete-request/${requestId}/confirm`, {
    method: "POST",
  })
  if (!resp.ok) throw new Error("确认删除失败")
}

/** 取消删除请求 */
export async function cancelAccountDeletion(requestId: string): Promise<void> {
  const resp = await authFetch(`${API_BASE}/user/delete-request/${requestId}/cancel`, {
    method: "POST",
  })
  if (!resp.ok) throw new Error("取消删除失败")
}

// ==================== 知识库 ====================

/** 获取知识库列表 */
export async function getKnowledgeBases(): Promise<any> {
  const resp = await authFetch(`${API_BASE}/knowledge-bases`)
  if (!resp.ok) throw new Error("获取知识库列表失败")
  return resp.json()
}

/** 创建知识库 */
export async function createKnowledgeBase(name: string, description?: string): Promise<any> {
  const resp = await authFetch(`${API_BASE}/knowledge-bases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description: description || "" }),
  })
  return resp.json()
}

// ==================== 文档管理 ====================

/** 上传文档 */
export async function uploadDocument(kbId: string, file: File): Promise<DocumentUploadResult> {
  const formData = new FormData()
  formData.append("file", file)

  const resp = await authFetch(`${API_BASE}/knowledge-bases/${kbId}/documents/upload`, {
    method: "POST",
    body: formData,
  })

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw new Error(body.detail || body.error || `上传失败 (${resp.status})`)
  }

  return resp.json()
}

/** 查询文档索引状态 */
export async function getDocumentStatus(kbId: string, docId: string): Promise<DocumentStatus> {
  const resp = await authFetch(`${API_BASE}/knowledge-bases/${kbId}/documents/${docId}/status`)
  if (!resp.ok) throw new Error("查询文档状态失败")
  return resp.json()
}

/** 删除文档 */
export async function deleteDocument(kbId: string, docId: string): Promise<void> {
  await authFetch(`${API_BASE}/knowledge-bases/${kbId}/documents/${docId}`, {
    method: "DELETE",
  })
}

// ==================== 核心问答 (SSE 流式) ====================

/**
 * 知识库问答 — SSE 流式响应
 *
 * 通过 POST 请求 + ReadableStream 解析 SSE 事件流，
 * 实现打字机效果的实时对话。
 *
 * 后端 SSE 事件格式:
 *   data: {"type":"token","content":"..."}
 *   data: {"type":"metadata","conversation_id":"..."}
 *   data: {"type":"done","sources":[...]}
 *   data: {"type":"error","content":"..."}
 */
export async function chatStream(options: ChatOptions) {
  const { kbId, question, conversationId, history, onToken, onMetadata, onSources, onError, onDone } = options

  try {
    const response = await authFetch(`${API_BASE}/knowledge-bases/${kbId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        conversation_id: conversationId,
        history,
      }),
    })

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      onError(body.error || body.detail || `请求失败 (${response.status})`)
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      onError("无法读取响应流")
      return
    }

    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n")
      buffer = lines.pop() || ""

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6))
            switch (data.type) {
              case "token":
                onToken(data.content)
                break
              case "metadata":
                onMetadata(data)
                break
              case "done":
                if (data.sources) onSources(data.sources)
                onDone()
                return
              case "error":
                onError(data.content)
                break
            }
          } catch {
            // 忽略无法解析的 JSON 行
          }
        }
      }
    }
    onDone()
  } catch (err: any) {
    if (err.name === "AuthError") {
      onError("登录已过期，请刷新页面重新登录")
    } else {
      onError(err.message || "网络错误")
    }
  }
}

// ==================== 管理 ====================

/** 获取系统统计 */
export async function getSystemStats(): Promise<SystemStats> {
  const resp = await authFetch(`${API_BASE}/admin/stats`)
  if (!resp.ok) throw new Error("获取系统统计失败")
  return resp.json()
}

/** 管理员触发数据清理 */
export async function adminCleanup(): Promise<any> {
  const resp = await authFetch(`${API_BASE}/admin/cleanup`, { method: "POST" })
  if (!resp.ok) throw new Error("数据清理失败")
  return resp.json()
}
