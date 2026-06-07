"use client"

import { useState, useRef, useCallback, useEffect } from "react"
import { chatStream } from "@/lib/api"

export interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  sources?: any[]
  timestamp: Date
}

/** 生成唯一 ID */
function uid(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export function useChat(kbId: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string>()
  const [sources, setSources] = useState<any[]>([])

  const messagesEndRef = useRef<HTMLDivElement>(null)
  // 用 ref 持有最新 messages，避免 send 函数因 messages 变更而重建
  const messagesRef = useRef<Message[]>([])
  messagesRef.current = messages

  // 自动滚动到最新消息
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const send = useCallback(async (question: string) => {
    if (!question.trim() || isLoading) return

    const userMessage: Message = {
      id: uid(),
      role: "user",
      content: question,
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setIsLoading(true)
    setSources([])

    const assistantMessageId = uid()
    setMessages((prev) => [
      ...prev,
      { id: assistantMessageId, role: "assistant", content: "", timestamp: new Date() },
    ])

    // 通过 ref 获取最新 messages，避免依赖数组引用状态变量
    const history = messagesRef.current.map((m) => ({
      role: m.role,
      content: m.content,
    }))

    try {
      await chatStream({
        kbId,
        question,
        conversationId,
        history,
        onToken: (token) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId ? { ...m, content: m.content + token } : m
            )
          )
        },
        onMetadata: (meta) => {
          if (meta.conversation_id) setConversationId(meta.conversation_id)
        },
        onSources: (srcs) => {
          setSources(srcs)
        },
        onError: (error) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? { ...m, content: `\u26A0\uFE0F ${error}` }
                : m
            )
          )
          setIsLoading(false)
        },
        onDone: () => {
          setIsLoading(false)
        },
      })
    } catch {
      setIsLoading(false)
    }
  }, [kbId, isLoading, conversationId]) // messages 通过 ref 获取，不在依赖数组中

  const clear = useCallback(() => {
    setMessages([])
    setConversationId(undefined)
    setSources([])
  }, [])

  return {
    messages,
    isLoading,
    conversationId,
    sources,
    messagesEndRef,
    send,
    clear,
    setSources,
  }
}
