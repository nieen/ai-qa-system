"use client"

import React from "react"
import ChatInterface from "@/components/ChatInterface"

export default function Home() {
  return (
    <main className="h-screen flex flex-col">
      {/* 顶栏 */}
      <header className="bg-blue-700 text-white px-6 py-3 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-white/20 rounded-lg flex items-center justify-center text-sm font-bold">
            AI
          </div>
          <div>
            <h1 className="text-lg font-semibold">企业 AI 智能问答系统</h1>
            <p className="text-xs text-blue-200">基于 DeepSeek + RAG 技术</p>
          </div>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-blue-200">状态: </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
            <span>运行中</span>
          </span>
        </div>
      </header>

      {/* 主体 - 全高聊天界面 */}
      <div className="flex-1 overflow-hidden">
        <ChatInterface kbId="default" kbName="默认知识库" />
      </div>
    </main>
  )
}
