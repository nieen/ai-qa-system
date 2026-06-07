"use client"

import React, { useState, useEffect } from "react"
import {
  LogIn, UserPlus, LogOut, User, Shield, Moon, Sun, Monitor,
  Download, Trash2, Settings, AlertTriangle,
} from "lucide-react"
import ChatInterface from "@/components/ChatInterface"
import AuthModal from "@/components/AuthModal"
import { Button } from "@/components/ui/button"
import {
  login as apiLogin,
  logout as apiLogout,
  exportUserData,
  requestAccountDeletion,
  confirmAccountDeletion,
  cancelAccountDeletion,
  type LoginResult,
} from "@/lib/api"
import {
  getToken,
  getStoredUser,
  setToken,
  clearToken,
  setStoredUser,
  type AuthUser,
} from "@/lib/auth"

// ==================== 主题管理 ====================

type Theme = "light" | "dark" | "system"

function useTheme() {
  const [theme, setThemeState] = useState<Theme>("system")

  useEffect(() => {
    const stored = localStorage.getItem("aiqa_theme") as Theme | null
    if (stored) setThemeState(stored)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    const isDark =
      theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)

    root.classList.toggle("dark", isDark)
    localStorage.setItem("aiqa_theme", theme)
  }, [theme])

  // 监听系统主题变化
  useEffect(() => {
    if (theme !== "system") return
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const handler = () => {
      document.documentElement.classList.toggle("dark", mq.matches)
    }
    mq.addEventListener("change", handler)
    return () => mq.removeEventListener("change", handler)
  }, [theme])

  const cycleTheme = () => {
    setThemeState((prev) => {
      if (prev === "light") return "dark"
      if (prev === "dark") return "system"
      return "light"
    })
  }

  const themeIcon = theme === "dark" ? <Moon className="w-4 h-4" /> :
    theme === "light" ? <Sun className="w-4 h-4" /> :
      <Monitor className="w-4 h-4" />

  const themeLabel = theme === "dark" ? "暗色" : theme === "light" ? "亮色" : "跟随系统"

  return { theme, themeIcon, themeLabel, cycleTheme }
}

// ==================== 数据合规弹窗 ====================

function ConfirmModal({
  title,
  message,
  confirmText,
  danger,
  onConfirm,
  onCancel,
  loading,
}: {
  title: string
  message: string
  confirmText: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
  loading?: boolean
}) {
  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6 space-y-4">
        <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100">{title}</h3>
        <p className="text-sm text-gray-600 dark:text-gray-400">{message}</p>
        <div className="flex gap-3 justify-end">
          <Button variant="outline" onClick={onCancel} disabled={loading}>
            取消
          </Button>
          <Button
            onClick={onConfirm}
            disabled={loading}
            className={danger ? "!bg-red-600 hover:!bg-red-700" : ""}
          >
            {loading ? "处理中..." : confirmText}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ==================== 首页 ====================

export default function Home() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [showAuthModal, setShowAuthModal] = useState<"login" | "register" | null>(null)
  const [confirmAction, setConfirmAction] = useState<string | null>(null)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [confirmResult, setConfirmResult] = useState<string | null>(null)
  const { themeIcon, themeLabel, cycleTheme } = useTheme()

  // 初始化时从 localStorage 恢复登录状态
  useEffect(() => {
    const token = getToken()
    const storedUser = getStoredUser()
    if (token && storedUser) {
      setUser(storedUser)
    }
  }, [])

  const handleLoginSuccess = (result: LoginResult) => {
    setUser(result.user)
    setShowAuthModal(null)
  }

  const handleLogout = async () => {
    try {
      await apiLogout()
    } catch {
      // 即使登出 API 调用失败，也清除本地状态
    }
    setUser(null)
    clearToken()
  }

  // ---- 数据合规操作 ----

  const handleExportData = async () => {
    setConfirmLoading(true)
    try {
      const data = await exportUserData()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `my-data-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      setConfirmResult("数据导出成功，已开始下载")
    } catch (err: any) {
      setConfirmResult(`导出失败: ${err.message}`)
    } finally {
      setConfirmLoading(false)
      setConfirmAction(null)
      setTimeout(() => setConfirmResult(null), 5000)
    }
  }

  const handleRequestDeletion = async () => {
    setConfirmLoading(true)
    try {
      const requestId = await requestAccountDeletion()
      setConfirmResult(`删除请求已提交（ID: ${requestId.slice(0, 8)}...），请在 7 天内确认。`)
    } catch (err: any) {
      setConfirmResult(`提交失败: ${err.message}`)
    } finally {
      setConfirmLoading(false)
      setConfirmAction(null)
      setTimeout(() => setConfirmResult(null), 8000)
    }
  }

  // ==================== 渲染 ====================

  return (
    <main className="h-screen flex flex-col bg-gray-50 dark:bg-gray-950 transition-colors">
      {/* 顶栏 */}
      <header className="bg-blue-700 dark:bg-blue-900 text-white px-6 py-3 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-white/20 rounded-lg flex items-center justify-center text-sm font-bold">
            AI
          </div>
          <div>
            <h1 className="text-lg font-semibold">企业 AI 智能问答系统</h1>
            <p className="text-xs text-blue-200 dark:text-blue-300">基于 DeepSeek + RAG 技术</p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-sm">
          {/* 主题切换 */}
          <button
            onClick={cycleTheme}
            className="flex items-center gap-1 px-2 py-1.5 rounded-lg hover:bg-white/20 transition-colors text-blue-200 hover:text-white"
            aria-label={`当前主题: ${themeLabel}`}
            title={themeLabel}
          >
            {themeIcon}
          </button>

          {user ? (
            <>
              {user.role === "admin" && (
                <span className="flex items-center gap-1 text-amber-200 text-xs mr-1">
                  <Shield className="w-3 h-3" />
                  管理员
                </span>
              )}
              <span className="flex items-center gap-1.5 text-blue-200">
                <User className="w-4 h-4" />
                <span>{user.display_name || user.username}</span>
              </span>

              {/* 数据合规菜单 */}
              <div className="relative group">
                <button className="flex items-center gap-1 px-2 py-1.5 rounded-lg hover:bg-white/20 transition-colors text-blue-200 hover:text-white">
                  <Settings className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">设置</span>
                </button>
                <div className="absolute right-0 top-full mt-1 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-xl border dark:border-gray-700 hidden group-hover:block z-40">
                  <div className="py-1">
                    <button
                      onClick={() => setConfirmAction("export")}
                      className="w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
                    >
                      <Download className="w-4 h-4" />
                      导出个人数据
                    </button>
                    <button
                      onClick={() => setConfirmAction("delete")}
                      className="w-full text-left px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
                    >
                      <Trash2 className="w-4 h-4" />
                      注销账号
                    </button>
                  </div>
                </div>
              </div>

              <button
                onClick={handleLogout}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg hover:bg-white/20 transition-colors text-blue-200 hover:text-white"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">退出</span>
              </button>
            </>
          ) : (
            <>
              <span className="text-blue-200">未登录</span>
              <button
                onClick={() => setShowAuthModal("login")}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white/15 hover:bg-white/25 transition-colors"
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>登录</span>
              </button>
              <button
                onClick={() => setShowAuthModal("register")}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white/15 hover:bg-white/25 transition-colors"
              >
                <UserPlus className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">注册</span>
              </button>
            </>
          )}
        </div>
      </header>

      {/* 操作结果提示 */}
      {confirmResult && (
        <div
          className="px-6 py-2 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300 text-sm flex items-center gap-2 border-b dark:border-green-800"
          role="status"
          aria-live="polite"
        >
          <AlertTriangle className="w-4 h-4" />
          {confirmResult}
        </div>
      )}

      {/* 主体 */}
      {user ? (
        <div className="flex-1 overflow-hidden">
          <ChatInterface kbId="default" kbName="默认知识库" />
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center bg-gray-50 dark:bg-gray-950">
          <div className="text-center max-w-md mx-auto px-6">
            <div className="w-20 h-20 bg-blue-100 dark:bg-blue-900 rounded-2xl flex items-center justify-center mx-auto mb-6">
              <LogIn className="w-10 h-10 text-blue-600 dark:text-blue-400" />
            </div>
            <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-2">
              欢迎使用企业 AI 智能问答系统
            </h2>
            <p className="text-gray-500 dark:text-gray-400 mb-8 leading-relaxed">
              请登录或注册以开始使用。
              <br />
              登录后可以上传文档到知识库，并向 AI 提问。
            </p>
            <div className="flex gap-3 justify-center">
              <Button size="lg" onClick={() => setShowAuthModal("login")}>
                <LogIn className="w-4 h-4 mr-2" />
                登录
              </Button>
              <Button variant="outline" size="lg" onClick={() => setShowAuthModal("register")}>
                <UserPlus className="w-4 h-4 mr-2" />
                注册
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 登录/注册模态框 */}
      {showAuthModal && (
        <AuthModal
          mode={showAuthModal}
          onClose={() => setShowAuthModal(null)}
          onSuccess={handleLoginSuccess}
        />
      )}

      {/* 数据合规确认框 */}
      {confirmAction === "export" && (
        <ConfirmModal
          title="导出个人数据"
          message="系统将导出您的个人资料、对话历史和上传的文档。数据以 JSON 格式下载。"
          confirmText="导出"
          onConfirm={handleExportData}
          onCancel={() => setConfirmAction(null)}
          loading={confirmLoading}
        />
      )}
      {confirmAction === "delete" && (
        <ConfirmModal
          title="注销账号"
          message="注销后您的账号和所有关联数据将被永久删除，此操作不可逆。确认后将有 7 天冷静期。"
          confirmText="确认注销"
          danger
          onConfirm={handleRequestDeletion}
          onCancel={() => setConfirmAction(null)}
          loading={confirmLoading}
        />
      )}
    </main>
  )
}
