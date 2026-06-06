"use client"

import React, { useState, useEffect, useRef } from "react"
import { X, AlertCircle, CheckCircle2, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { login as apiLogin, register as apiRegister, type LoginResult } from "@/lib/api"
import { setToken, setStoredUser } from "@/lib/auth"

interface AuthModalProps {
  mode: "login" | "register"
  onClose: () => void
  onSuccess: (result: LoginResult) => void
}

export default function AuthModal({ mode, onClose, onSuccess }: AuthModalProps) {
  const [isRegister, setIsRegister] = useState(mode === "register")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [email, setEmail] = useState("")
  const [agreed, setAgreed] = useState(false)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)

  const usernameRef = useRef<HTMLInputElement>(null)

  // 打开时自动聚焦到用户名输入框
  useEffect(() => {
    setTimeout(() => usernameRef.current?.focus(), 50)
  }, [])

  // ESC 键关闭
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handleEsc)
    return () => window.removeEventListener("keydown", handleEsc)
  }, [onClose])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setLoading(true)

    try {
      if (isRegister) {
        if (!agreed) {
          setError("请阅读并同意隐私政策")
          setLoading(false)
          return
        }
        const result = await apiRegister(username, password, { display_name: displayName, email })
        if (result.user) {
          setSuccess(true)
          setTimeout(() => {
            setIsRegister(false)
            setSuccess(false)
            setPassword("")
          }, 1500)
        }
      } else {
        const result = await apiLogin(username, password)
        setToken(result.token)
        setStoredUser(result.user)
        onSuccess(result)
      }
    } catch (err: any) {
      setError(err.message || "操作失败")
    } finally {
      setLoading(false)
    }
  }

  const switchMode = () => {
    setIsRegister(!isRegister)
    setError("")
    setPassword("")
    setSuccess(false)
  }

  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50"
      role="dialog"
      aria-modal="true"
      aria-label={isRegister ? "创建账号" : "登录"}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="bg-blue-700 dark:bg-blue-800 text-white px-6 py-5 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">{isRegister ? "创建账号" : "登录"}</h2>
            <p className="text-xs text-blue-200 dark:text-blue-300 mt-0.5">
              {isRegister ? "注册后即可使用企业 AI 智能问答系统" : "使用账号登录以继续"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-white/20 rounded-lg transition-colors"
            aria-label="关闭"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4 dark:text-gray-200">
          {success && (
            <div
              className="flex items-center gap-2 text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/30 px-4 py-3 rounded-lg text-sm"
              role="status"
              aria-live="polite"
            >
              <CheckCircle2 className="w-5 h-5 flex-shrink-0" />
              <span>注册成功！即将跳转到登录...</span>
            </div>
          )}

          <div>
            <label htmlFor="auth-username" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              用户名
            </label>
            <Input
              ref={usernameRef}
              id="auth-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              required
              minLength={2}
              disabled={loading || success}
              autoComplete="username"
            />
          </div>

          <div>
            <label htmlFor="auth-password" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              密码
            </label>
            <Input
              id="auth-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码（至少6位）"
              required
              minLength={6}
              disabled={loading || success}
              autoComplete={isRegister ? "new-password" : "current-password"}
            />
          </div>

          {isRegister && (
            <>
              <div>
                <label htmlFor="auth-display" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  显示名称 <span className="text-gray-400">(可选)</span>
                </label>
                <Input
                  id="auth-display"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="你的显示名称"
                  disabled={loading || success}
                />
              </div>
              <div>
                <label htmlFor="auth-email" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  邮箱 <span className="text-gray-400">(可选)</span>
                </label>
                <Input
                  id="auth-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  disabled={loading || success}
                />
              </div>
              <label className="flex items-start gap-2 text-sm text-gray-600 dark:text-gray-400">
                <input
                  type="checkbox"
                  checked={agreed}
                  onChange={(e) => setAgreed(e.target.checked)}
                  className="mt-1"
                  disabled={loading || success}
                />
                <span>
                  我已阅读并同意{" "}
                  <span className="text-blue-600 dark:text-blue-400 underline cursor-pointer">
                    隐私政策
                  </span>
                  ，了解个人信息的收集和使用方式
                </span>
              </label>
            </>
          )}

          {error && (
            <div
              className="flex items-center gap-2 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30 px-4 py-3 rounded-lg text-sm"
              role="alert"
              aria-live="assertive"
            >
              <AlertCircle className="w-5 h-5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <Button type="submit" disabled={loading || success} className="w-full">
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                处理中...
              </>
            ) : isRegister ? (
              "注册"
            ) : (
              "登录"
            )}
          </Button>

          <div className="text-center text-sm text-gray-500 dark:text-gray-400">
            {isRegister ? (
              <span>
                已有账号？{" "}
                <button type="button" onClick={switchMode} className="text-blue-600 dark:text-blue-400 hover:underline">
                  去登录
                </button>
              </span>
            ) : (
              <span>
                没有账号？{" "}
                <button type="button" onClick={switchMode} className="text-blue-600 dark:text-blue-400 hover:underline">
                  去注册
                </button>
              </span>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}
