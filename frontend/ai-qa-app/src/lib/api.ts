"use client"

/**
 * API 客户端
 * 处理与 RAG 服务的所有通信
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080/api/v1"

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

export async function chatStream(options: ChatOptions) {
  const { kbId, question, conversationId, history, onToken, onMetadata, onSources, onError, onDone } = options

  try {
    const response = await fetch(`${API_BASE}/knowledge-bases/${kbId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        conversation_id: conversationId,
        history,
      }),
    })

    if (!response.ok) {
      onError(`请求失败 (${response.status})`)
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
                break
              case "error":
                onError(data.content)
                break
            }
          } catch {
            // 忽略无法解析的行
          }
        }
      }
    }
    onDone()
  } catch (err: any) {
    onError(err.message || "网络错误")
  }
}

export async function uploadDocument(kbId: string, file: File) {
  const formData = new FormData()
  formData.append("file", file)

  const response = await fetch(`${API_BASE}/knowledge-bases/${kbId}/documents/upload`, {
    method: "POST",
    body: formData,
  })
  return response.json()
}

export async function login(username: string, password: string) {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  return response.json()
}

export async function getKnowledgeBases() {
  const response = await fetch(`${API_BASE}/knowledge-bases`)
  return response.json()
}

export async function getSystemStats() {
  const response = await fetch(`${API_BASE}/admin/stats`)
  return response.json()
}
