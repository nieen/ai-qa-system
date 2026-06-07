"use client"

/**
 * API 客户端
 *
 * 通过 Next.js API Routes (BFF) 调用 Go API 网关。
 * 浏览器同源请求 /api/*，Next.js 服务端转发到网关，无需 CORS。
 *
 * 后端架构:
 *   前端 /api/* → Next.js BFF → 网关 (8080) → RAG 服务 (8001) → Milvus + PG + Redis
 */

import { getToken, clearToken, authHeaders } from "./auth"

// 所有请求走同源 /api/*，由 Next.js API Routes 转发到网关
// 服务端直连时使用 API_BASE (server-only env)
const API_PREFIX = "/api"

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

export interface KnowledgeBase {
  id: string
  name: string
  description?: string
  document_count?: number
  created_at?: string
}

export interface UserExportData {
  user: UserProfile
  conversations: any[]
  documents: any[]
  exported_at: string
}

export interface CleanupResult {
  message: string
  deleted_logs?: number
  deleted_conversations?: number
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

/** 统一的错误消息提取：兼容 Go 网关 {error, code} 和 RAG 服务 {detail} 两种响应格式 */
function extractErrorMessage(body: any, fallback: string): string {
  return body?.error || body?.detail || fallback
}

// ==================== 认证 ====================

/** 用户登录 — 返回 JWT Token */
export async function login(username: string, password: string): Promise<LoginResult> {
  const resp = await fetch(`/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw new Error(extractErrorMessage(body, `登录失败 (${resp.status})`))
  }

  return resp.json()
}

/** 用户注册 — 需同意隐私政策 */
export async function register(
  username: string,
  password: string,
  options?: { display_name?: string; email?: string }
): Promise<RegisterResult> {
  const resp = await fetch(`/auth/register`, {
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
    throw new Error(extractErrorMessage(body, `注册失败 (${resp.status})`))
  }

  return resp.json()
}

/** 用户登出 — 将当前 Token 加入黑名单 */
export async function logout(): Promise<void> {
  const token = getToken()
  if (!token) return

  try {
    await authFetch(`/user/logout`, { method: "POST" })
  } catch {
    // 即使登出请求失败，也清除本地 Token
  } finally {
    clearToken()
  }
}

// ==================== 用户管理 ====================

/** 获取当前用户信息 */
export async function getProfile(): Promise<UserProfile> {
  const resp = await authFetch(`/user/profile`)
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw new Error(body.error || `获取用户信息失败 (${resp.status})`)
  }
  return resp.json()
}

/** 导出个人数据 (PIPL §45) */
export async function exportUserData(): Promise<UserExportData> {
  const resp = await authFetch(`/user/export`)
  if (!resp.ok) throw new Error("导出失败")
  return resp.json()
}

/** 请求删除账号 (PIPL §47), 返回 request_id */
export async function requestAccountDeletion(): Promise<string> {
  const resp = await authFetch(`/user/delete-request`, { method: "POST" })
  if (!resp.ok) throw new Error("删除请求提交失败")
  const data = await resp.json()
  return data.request_id
}

/** 确认删除账号 */
export async function confirmAccountDeletion(requestId: string): Promise<void> {
  const resp = await authFetch(`/user/delete-request/${requestId}/confirm`, {
    method: "POST",
  })
  if (!resp.ok) throw new Error("确认删除失败")
}

/** 取消删除请求 */
export async function cancelAccountDeletion(requestId: string): Promise<void> {
  const resp = await authFetch(`/user/delete-request/${requestId}/cancel`, {
    method: "POST",
  })
  if (!resp.ok) throw new Error("取消删除失败")
}

// ==================== 知识库 ====================

/** 获取知识库列表 */
export async function getKnowledgeBases(): Promise<KnowledgeBase[]> {
  const resp = await authFetch(`/knowledge-bases`)
  if (!resp.ok) throw new Error("获取知识库列表失败")
  return resp.json()
}

/** 创建知识库 */
export async function createKnowledgeBase(name: string, description?: string): Promise<KnowledgeBase> {
  const resp = await authFetch(`/knowledge-bases`, {
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

  const resp = await authFetch(`/knowledge-bases/${kbId}/documents/upload`, {
    method: "POST",
    body: formData,
  })

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw new Error(extractErrorMessage(body, `上传失败 (${resp.status})`))
  }

  return resp.json()
}

/** 查询文档索引状态 */
export async function getDocumentStatus(kbId: string, docId: string): Promise<DocumentStatus> {
  const resp = await authFetch(`/knowledge-bases/${kbId}/documents/${docId}/status`)
  if (!resp.ok) throw new Error("查询文档状态失败")
  return resp.json()
}

/** 删除文档 */
export async function deleteDocument(kbId: string, docId: string): Promise<void> {
  await authFetch(`/knowledge-bases/${kbId}/documents/${docId}`, {
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
    const response = await authFetch(`/knowledge-bases/${kbId}/chat`, {
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
      onError(extractErrorMessage(body, `请求失败 (${response.status})`))
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
              case "llm.error":
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
  const resp = await authFetch(`/admin/stats`)
  if (!resp.ok) throw new Error("获取系统统计失败")
  return resp.json()
}

/** 管理员触发数据清理 */
export async function adminCleanup(): Promise<CleanupResult> {
  const resp = await authFetch(`/admin/cleanup`, { method: "POST" })
  if (!resp.ok) throw new Error("数据清理失败")
  return resp.json()
}
