"use client"

import React, { useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Send, Loader2, Upload, FileText, MessageSquare, BookOpen, Trash2, CheckCircle, XCircle, Clock, Copy, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useChat, type Message } from "@/hooks/useChat"
import { useDocumentUpload, type UploadState } from "@/hooks/useDocumentUpload"

interface ChatInterfaceProps {
  kbId: string
  kbName: string
  onSelectKb?: () => void
}

/** 获取来源文件的显示名 */
function getSourceName(s: any, index: number): string {
  return s.source_file || s.source || `来源 ${index + 1}`
}

/** 获取来源相关度分数 */
function getSourceScore(s: any): string {
  const score = s.rerank_score ?? s.score ?? 0
  return (score * 100).toFixed(1)
}

/** 获取来源内容预览 */
function getSourcePreview(s: any): string {
  return s.content_preview || s.content?.slice(0, 200) || ""
}

// ==================== 消息气泡 ====================

function MessageBubble({
  message,
  isLoading,
}: {
  message: Message
  isLoading: boolean
}) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // 忽略
    }
  }

  return (
    <div className={`flex ${message.role === "user" ? "justify-end" : "justify-start"} group`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 relative ${
          message.role === "user"
            ? "bg-blue-600 dark:bg-blue-700 text-white rounded-br-md"
            : "bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 border dark:border-gray-700 rounded-bl-md shadow-sm"
        }`}
      >
        {message.role === "assistant" ? (
          <>
            {message.content ? (
              <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:text-gray-800 dark:prose-headings:text-gray-100 prose-p:text-gray-700 dark:prose-p:text-gray-300 prose-code:bg-gray-100 dark:prose-code:bg-gray-700 prose-code:px-1 prose-code:rounded">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>
            ) : isLoading ? (
              <div className="flex items-center gap-2 text-gray-400 dark:text-gray-500">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-sm">正在思考...</span>
              </div>
            ) : null}
            {message.content && (
              <button
                onClick={handleCopy}
                className="absolute -top-2 -right-2 p-1.5 rounded-full bg-gray-100 dark:bg-gray-700 border dark:border-gray-600 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-200 dark:hover:bg-gray-600"
                aria-label="复制消息"
              >
                {copied ? (
                  <Check className="w-3 h-3 text-green-600" />
                ) : (
                  <Copy className="w-3 h-3 text-gray-500" />
                )}
              </button>
            )}
          </>
        ) : (
          <div className="text-sm">{message.content}</div>
        )}
      </div>
    </div>
  )
}

// ==================== 文档上传状态消息 ====================

function UploadStatusMessage({ state }: { state: UploadState }) {
  const iconMap = {
    idle: null,
    uploading: <Loader2 className="w-4 h-4 animate-spin text-blue-500" />,
    processing: <Clock className="w-4 h-4 text-amber-500" />,
    completed: <CheckCircle className="w-4 h-4 text-green-500" />,
    failed: <XCircle className="w-4 h-4 text-red-500" />,
    timeout: <Clock className="w-4 h-4 text-amber-500" />,
  }

  const titleMap: Record<string, string> = {
    uploading: `\uD83D\uDCE4 正在上传 **${state.fileName}**...`,
    processing: `\uD83D\uDCC4 文档 **${state.fileName}** 已加入索引队列\n\n- 文件类型: ${state.fileType}\n- 状态: 处理中...\n- 消息: ${state.message}`,
    completed: `\u2705 文档 **${state.fileName}** 索引完成！\n\n- 文件类型: ${state.fileType}\n- 分块数: ${state.chunkCount ?? "未知"}\n- 状态: 已完成`,
    failed: `\u274C 文档 **${state.fileName}** 索引失败\n\n- 错误: ${state.message}\n\n请尝试重新上传。`,
    timeout: `\u26A0\uFE0F 文档 **${state.fileName}** 索引超时\n\n- 状态: 处理中可能仍在后台运行\n- 建议稍后查看知识库文档列表确认`,
  }

  if (state.status === "idle") return null

  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl px-4 py-3 bg-white dark:bg-gray-800 border dark:border-gray-700 rounded-bl-md shadow-sm">
        <div className="prose prose-sm max-w-none dark:prose-invert">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {titleMap[state.status] || ""}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  )
}

// ==================== 空状态 ====================

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-gray-400 dark:text-gray-500 space-y-3">
      <MessageSquare className="w-16 h-16" />
      <h3 className="text-lg font-medium text-gray-500 dark:text-gray-400">
        企业 AI 智能问答
      </h3>
      <p className="text-sm text-center max-w-md">
        上传文档到知识库，然后开始提问。
        <br />
        系统将基于知识库内容用 AI 为您解答。
      </p>
    </div>
  )
}

// ==================== 首次加载骨架屏 ====================

function LoadingSkeleton() {
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl px-4 py-4 bg-white dark:bg-gray-800 border dark:border-gray-700 rounded-bl-md shadow-sm space-y-3 w-96">
        <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded animate-pulse w-3/4" />
        <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded animate-pulse w-1/2" />
        <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded animate-pulse w-5/6" />
      </div>
    </div>
  )
}

// ==================== 来源面板 ====================

function SourcePanel({
  sources,
  show,
  onToggle,
}: {
  sources: any[]
  show: boolean
  onToggle: () => void
}) {
  if (sources.length === 0) return null

  return (
    <div className="px-6 py-2 border-t dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
      <button
        onClick={onToggle}
        className="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 flex items-center gap-1"
        aria-expanded={show}
        aria-controls="source-panel"
      >
        <FileText className="w-3 h-3" />
        {show ? "隐藏" : "查看"}参考来源 ({sources.length})
      </button>
      {show && (
        <div
          id="source-panel"
          className="mt-2 space-y-2 max-h-32 overflow-y-auto"
          role="list"
          aria-label="参考来源列表"
        >
          {sources.map((s, i) => (
            <div
              key={`${getSourceName(s, i)}-${i}`}
              className="text-xs bg-white dark:bg-gray-700 rounded p-2 border dark:border-gray-600"
              role="listitem"
            >
              <div className="text-gray-500 dark:text-gray-400">
                {getSourceName(s, i)}
                <span className="ml-2 text-blue-500 dark:text-blue-400">
                  相关度: {getSourceScore(s)}%
                </span>
              </div>
              <div className="text-gray-600 dark:text-gray-300 mt-1 line-clamp-2">
                {getSourcePreview(s)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ==================== 主组件 ====================

export default function ChatInterface({ kbId, kbName, onSelectKb }: ChatInterfaceProps) {
  const {
    messages,
    isLoading,
    sources,
    messagesEndRef,
    send,
    clear,
    setSources,
  } = useChat(kbId)

  const { uploadState, isUploading, upload, reset: resetUpload } = useDocumentUpload(kbId)

  const [input, setInput] = useState("")
  const [showSources, setShowSources] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleSend = () => {
    send(input)
    setInput("")
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

    await upload(file)

    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const handleClear = () => {
    clear()
    resetUpload()
  }

  return (
    <div className="flex flex-col h-full">
      {/* 头部 */}
      <div className="flex items-center justify-between px-6 py-3 border-b dark:border-gray-700 bg-white dark:bg-gray-900">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-blue-600 dark:text-blue-400" />
          <button
            onClick={onSelectKb}
            className="font-semibold text-gray-800 dark:text-gray-200 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
            aria-label="切换知识库"
          >
            {kbName}
          </button>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => fileInputRef.current?.click()} aria-label="上传文档">
            <Upload className="w-4 h-4 mr-1" />
            上传文档
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.doc,.md,.html,.htm,.txt"
            className="hidden"
            onChange={handleFileUpload}
            aria-hidden="true"
          />
          <Button variant="ghost" size="sm" onClick={handleClear} aria-label="清空对话">
            <Trash2 className="w-4 h-4 mr-1" />
            清空对话
          </Button>
        </div>
      </div>

      {/* 消息区域 */}
      <div
        className="flex-1 overflow-y-auto px-6 py-4 space-y-4 bg-gray-50 dark:bg-gray-900/50"
        role="log"
        aria-live="polite"
        aria-label="对话消息"
      >
        {messages.length === 0 && uploadState.status === "idle" && !isUploading && <EmptyState />}

        {uploadState.status !== "idle" && <UploadStatusMessage state={uploadState} />}

        {messages.length === 0 && isUploading && <LoadingSkeleton />}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} isLoading={isLoading} />
        ))}

        <div ref={messagesEndRef} />
      </div>

      {/* 来源面板 */}
      <SourcePanel
        sources={sources}
        show={showSources}
        onToggle={() => setShowSources(!showSources)}
      />

      {/* 输入区域 */}
      <div className="px-6 py-4 border-t dark:border-gray-700 bg-white dark:bg-gray-900">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入你的问题..."
            disabled={isLoading || isUploading}
            className="flex-1"
            aria-label="输入问题"
          />
          <Button onClick={handleSend} disabled={isLoading || isUploading || !input.trim()} aria-label="发送">
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-2">
          Enter 发送，Shift+Enter 换行 · 支持 PDF、Word、Markdown、HTML、TXT
        </p>
      </div>
    </div>
  )
}
