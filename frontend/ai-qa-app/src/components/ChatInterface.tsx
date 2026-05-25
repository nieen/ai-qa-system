"use client"

import React, { useState, useRef, useEffect } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Send, Loader2, Upload, FileText, MessageSquare, BookOpen, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { chatStream, uploadDocument } from "@/lib/api"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  sources?: any[]
  timestamp: Date
}

interface ChatInterfaceProps {
  kbId: string
  kbName: string
}

export default function ChatInterface({ kbId, kbName }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string>()
  const [sources, setSources] = useState<any[]>([])
  const [showSources, setShowSources] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const handleSend = async () => {
    const question = input.trim()
    if (!question || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: question,
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput("")
    setIsLoading(true)
    setSources([])

    const assistantMessageId = (Date.now() + 1).toString()
    setMessages((prev) => [
      ...prev,
      { id: assistantMessageId, role: "assistant", content: "", timestamp: new Date() },
    ])

    const history = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }))

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
              ? { ...m, content: `⚠️ ${error}` }
              : m
          )
        )
      },
      onDone: () => {
        setIsLoading(false)
      },
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsLoading(true)
    try {
      const result = await uploadDocument(kbId, file)
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          role: "assistant",
          content: `✅ 文档 **${file.name}** 上传成功！\n\n- 文件类型: ${result.file_type}\n- 分块数: ${result.chunk_count}\n- 状态: ${result.status}`,
          timestamp: new Date(),
        },
      ])
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          role: "assistant",
          content: `❌ 文档上传失败: ${err.message}`,
          timestamp: new Date(),
        },
      ])
    } finally {
      setIsLoading(false)
    }

    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const clearChat = () => {
    setMessages([])
    setConversationId(undefined)
    setSources([])
  }

  return (
    <div className="flex flex-col h-full">
      {/* 头部 */}
      <div className="flex items-center justify-between px-6 py-3 border-b bg-white">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-blue-600" />
          <h2 className="font-semibold text-gray-800">{kbName}</h2>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => fileInputRef.current?.click()}>
            <Upload className="w-4 h-4 mr-1" />
            上传文档
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.doc,.md,.html,.htm,.txt"
            className="hidden"
            onChange={handleFileUpload}
          />
          <Button variant="ghost" size="sm" onClick={clearChat}>
            <Trash2 className="w-4 h-4 mr-1" />
            清空对话
          </Button>
        </div>
      </div>

      {/* 消息区域 */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 bg-gray-50">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-gray-400 space-y-3">
            <MessageSquare className="w-16 h-16" />
            <h3 className="text-lg font-medium text-gray-500">企业 AI 智能问答</h3>
            <p className="text-sm text-center max-w-md">
              上传文档到知识库，然后开始提问。
              <br />
              系统将基于知识库内容用 AI 为您解答。
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-blue-600 text-white rounded-br-md"
                  : "bg-white text-gray-800 border rounded-bl-md shadow-sm"
              }`}
            >
              {msg.role === "assistant" ? (
                <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:text-gray-800 prose-p:text-gray-700 prose-code:bg-gray-100 prose-code:px-1 prose-code:rounded">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content || (isLoading ? "" : "")}
                  </ReactMarkdown>
                  {isLoading && msg.content === "" && (
                    <div className="flex items-center gap-2 text-gray-400">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span className="text-sm">正在思考...</span>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-sm">{msg.content}</div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 来源面板 */}
      {sources.length > 0 && (
        <div className="px-6 py-2 border-t bg-gray-50">
          <button
            onClick={() => setShowSources(!showSources)}
            className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
          >
            <FileText className="w-3 h-3" />
            {showSources ? "隐藏" : "查看"}参考来源 ({sources.length})
          </button>
          {showSources && (
            <div className="mt-2 space-y-2 max-h-32 overflow-y-auto">
              {sources.map((s, i) => (
                <div key={i} className="text-xs bg-white rounded p-2 border">
                  <div className="text-gray-500">
                    {s.source_file || `来源 ${i + 1}`}
                    <span className="ml-2 text-blue-500">相关度: {(s.score * 100).toFixed(1)}%</span>
                  </div>
                  <div className="text-gray-600 mt-1 line-clamp-2">{s.content_preview}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 输入区域 */}
      <div className="px-6 py-4 border-t bg-white">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入你的问题..."
            disabled={isLoading}
            className="flex-1"
          />
          <Button onClick={handleSend} disabled={isLoading || !input.trim()}>
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>
        <p className="text-xs text-gray-400 mt-2">
          支持 PDF、Word、Markdown、HTML、TXT 格式文档上传
        </p>
      </div>
    </div>
  )
}
