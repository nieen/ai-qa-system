import { describe, it, expect, vi, beforeEach } from "vitest"
import { getToken, clearToken } from "@/lib/auth"

// Mock auth module
vi.mock("@/lib/auth", () => ({
  getToken: vi.fn(),
  clearToken: vi.fn(),
  authHeaders: vi.fn(() => ({})),
}))

// Mock global fetch
const mockFetch = vi.fn()
global.fetch = mockFetch

// Import after mocks
import { AuthError, chatStream } from "@/lib/api"

// Helper: create a ReadableStream from string chunks
function createMockStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    async start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
}

describe("chatStream SSE parsing", () => {
  const callbacks = {
    onToken: vi.fn(),
    onMetadata: vi.fn(),
    onSources: vi.fn(),
    onError: vi.fn(),
    onDone: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
    mockFetch.mockReset()
    vi.mocked(getToken).mockReturnValue("test-token")
  })

  it("calls onToken for each token event", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      body: createMockStream([
        'data: {"type":"token","content":"你好"}\n',
        'data: {"type":"token","content":"，"}\n',
        'data: {"type":"done","sources":[]}\n',
      ]),
    })

    await chatStream({
      kbId: "test",
      question: "测试",
      ...callbacks,
    })

    expect(callbacks.onToken).toHaveBeenCalledTimes(2)
    expect(callbacks.onToken).toHaveBeenNthCalledWith(1, "你好")
    expect(callbacks.onToken).toHaveBeenNthCalledWith(2, "，")
    expect(callbacks.onDone).toHaveBeenCalled()
  })

  it("calls onMetadata when metadata event received", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      body: createMockStream([
        'data: {"type":"metadata","conversation_id":"conv-123"}\n',
        'data: {"type":"token","content":"回答"}\n',
        'data: {"type":"done","sources":[]}\n',
      ]),
    })

    await chatStream({
      kbId: "test",
      question: "测试",
      ...callbacks,
    })

    expect(callbacks.onMetadata).toHaveBeenCalledWith(
      expect.objectContaining({ conversation_id: "conv-123" })
    )
  })

  it("calls onSources with the sources array on done", async () => {
    const sources = [{ source_file: "doc.pdf", score: 0.95 }]
    mockFetch.mockResolvedValue({
      ok: true,
      body: createMockStream([
        `data: {"type":"done","sources":${JSON.stringify(sources)}}\n`,
      ]),
    })

    await chatStream({
      kbId: "test",
      question: "测试",
      ...callbacks,
    })

    expect(callbacks.onSources).toHaveBeenCalledWith(sources)
    expect(callbacks.onDone).toHaveBeenCalled()
  })

  it("calls onError when response is not ok", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: vi.fn().mockResolvedValue({ error: "服务器错误" }),
    })

    await chatStream({
      kbId: "test",
      question: "测试",
      ...callbacks,
    })

    expect(callbacks.onError).toHaveBeenCalled()
    expect(callbacks.onDone).not.toHaveBeenCalled()
  })

  it("calls onError on network failure", async () => {
    mockFetch.mockRejectedValue(new Error("网络连接失败"))

    await chatStream({
      kbId: "test",
      question: "测试",
      ...callbacks,
    })

    expect(callbacks.onError).toHaveBeenCalledWith(expect.stringContaining("网络连接失败"))
  })

  it("handles AuthError on 401", async () => {
    mockFetch.mockRejectedValue(new AuthError("登录已过期"))

    await chatStream({
      kbId: "test",
      question: "测试",
      ...callbacks,
    })

    expect(callbacks.onError).toHaveBeenCalledWith(expect.stringContaining("登录已过期"))
  })

  it("handles cross-chunk SSE lines correctly", async () => {
    // "data: " split across two chunks
    mockFetch.mockResolvedValue({
      ok: true,
      body: createMockStream([
        'data: {"type":"token","con',
        'tent":"跨块"}\n',
        'data: {"type":"done","sources":[]}\n',
      ]),
    })

    await chatStream({
      kbId: "test",
      question: "测试",
      ...callbacks,
    })

    expect(callbacks.onToken).toHaveBeenCalledWith("跨块")
    expect(callbacks.onDone).toHaveBeenCalled()
  })
})
