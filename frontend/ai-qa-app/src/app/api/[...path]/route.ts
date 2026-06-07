/**
 * BFF (Backend For Frontend) API Route
 *
 * 浏览器同源调用 /api/*，此路由转发到 Go API 网关。
 * 优势:
 *   1. 无 CORS — 浏览器发请求到同源 /api，Next.js 服务端转发
 *   2. 支持 SSR/SSG — 服务端可直连网关（无需浏览器 Token）
 *   3. 未来可做 BFF 转换 — 裁剪/聚合网关响应
 *
 * 环境变量:
 *   API_BASE (服务端) — Go 网关地址，默认 http://gateway:8080/api/v1
 */
import { NextRequest, NextResponse } from "next/server"

const API_BASE = process.env.API_BASE || "http://gateway:8080/api/v1"

// ==================== 流式响应（SSE Chat）====================

async function handleStreamingResponse(
  gatewayResp: Response,
): Promise<Response> {
  if (!gatewayResp.body) {
    return NextResponse.json({ error: "网关无响应体" }, { status: 502 })
  }

  // 透传网关的 SSE 流
  const headers = new Headers({
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  })

  return new Response(gatewayResp.body, {
    status: gatewayResp.status,
    headers,
  })
}

// ==================== 常规 JSON 响应 ====================

async function handleJsonResponse(
  gatewayResp: Response,
): Promise<Response> {
  const body = await gatewayResp.text()
  return new Response(body, {
    status: gatewayResp.status,
    headers: {
      "Content-Type": gatewayResp.headers.get("Content-Type") || "application/json",
    },
  })
}

// ==================== 通用转发逻辑 ====================

async function proxyToGateway(
  request: NextRequest,
  gatewayPath: string,
): Promise<Response> {
  const url = `${gatewayPath}`

  // 构建转发 Headers
  const headers = new Headers()
  // 透传认证头 (浏览器传过来的 Authorization)
  const authHeader = request.headers.get("Authorization")
  if (authHeader) {
    headers.set("Authorization", authHeader)
  }
  // 透传 Content-Type
  const contentType = request.headers.get("Content-Type")
  if (contentType) {
    headers.set("Content-Type", contentType)
  }

  // 判断是否为 SSE 流式请求 — Chat 端点
  const isStreaming = gatewayPath.includes("/chat")

  try {
    const gatewayResp = await fetch(url, {
      method: request.method,
      headers,
      body: request.method !== "GET" && request.method !== "HEAD"
        ? await request.blob()
        : undefined,
      // 流式请求不断开
      signal: isStreaming ? undefined : AbortSignal.timeout(30000),
    })

    if (isStreaming && gatewayResp.ok) {
      return handleStreamingResponse(gatewayResp)
    }

    return handleJsonResponse(gatewayResp)
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "未知错误"
    return NextResponse.json(
      { error: `网关请求失败: ${message}`, code: "GATEWAY_ERROR" },
      { status: 502 },
    )
  }
}

// ==================== 路由处理 ====================

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params
  return proxyToGateway(request, "/" + path.join("/"))
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params
  return proxyToGateway(request, "/" + path.join("/"))
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params
  return proxyToGateway(request, "/" + path.join("/"))
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params
  return proxyToGateway(request, "/" + path.join("/"))
}
