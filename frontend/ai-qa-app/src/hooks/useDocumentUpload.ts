"use client"

import { useState, useCallback, useRef, useEffect } from "react"
import { uploadDocument, getDocumentStatus, type DocumentUploadResult, type DocumentStatus } from "@/lib/api"

/** 上传文档后轮询索引状态的最大次数（每次 2 秒，共 60 秒） */
const MAX_POLL_RETRIES = 30
const POLL_INTERVAL_MS = 2000

export interface UploadState {
  status: "idle" | "uploading" | "processing" | "completed" | "failed" | "timeout"
  fileName?: string
  fileType?: string
  message?: string
  chunkCount?: number
}

export function useDocumentUpload(kbId: string) {
  const [uploadState, setUploadState] = useState<UploadState>({ status: "idle" })
  const [isUploading, setIsUploading] = useState(false)
  const mountedRef = useRef(true)

  // 组件卸载时停止轮询
  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  const pollStatus = useCallback(
    async (docId: string): Promise<DocumentStatus> => {
      for (let i = 0; i < MAX_POLL_RETRIES; i++) {
        // 组件已卸载时提前退出轮询
        if (!mountedRef.current) {
          return { id: docId, status: "failed", message: "组件已卸载" }
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
        try {
          const status = await getDocumentStatus(kbId, docId)
          if (status.status === "completed" || status.status === "failed") {
            return { ...status, id: docId }
          }
        } catch {
          // 轮询失败继续等待
        }
      }
      return { id: docId, status: "failed", message: "索引超时" }
    },
    [kbId]
  )

  const upload = useCallback(
    async (file: File): Promise<UploadState> => {
      setIsUploading(true)
      setUploadState({ status: "uploading", fileName: file.name })

      try {
        const result: DocumentUploadResult = await uploadDocument(kbId, file)

        setUploadState({
          status: "processing",
          fileName: file.name,
          fileType: result.file_type,
          message: result.message,
        })

        if (result.id) {
          const finalStatus = await pollStatus(result.id)

          const newState: UploadState =
            finalStatus.status === "completed"
              ? {
                  status: "completed",
                  fileName: file.name,
                  fileType: result.file_type,
                  message: "索引完成",
                  chunkCount: finalStatus.chunk_count,
                }
              : finalStatus.status === "failed"
                ? {
                    status: "failed",
                    fileName: file.name,
                    message: finalStatus.message || "处理异常",
                  }
                : {
                    status: "timeout",
                    fileName: file.name,
                    message: "索引超时，可能仍在后台运行",
                  }

          setUploadState(newState)
          return newState
        }

        return { status: "failed", fileName: file.name, message: "上传返回异常" }
      } catch (err: any) {
        const failState: UploadState = {
          status: "failed",
          fileName: file.name,
          message: err.message || "上传失败",
        }
        setUploadState(failState)
        return failState
      } finally {
        setIsUploading(false)
      }
    },
    [kbId, pollStatus]
  )

  const reset = useCallback(() => {
    setUploadState({ status: "idle" })
  }, [])

  return { uploadState, isUploading, upload, reset }
}
