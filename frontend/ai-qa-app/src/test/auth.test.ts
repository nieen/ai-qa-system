import { describe, it, expect, beforeEach } from "vitest"
import {
  getToken,
  setToken,
  clearToken,
  getStoredUser,
  setStoredUser,
  isAuthenticated,
  isAdmin,
  authHeaders,
  type AuthUser,
} from "@/lib/auth"

describe("auth", () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe("getToken / setToken / clearToken", () => {
    it("returns null when no token is stored", () => {
      expect(getToken()).toBeNull()
    })

    it("returns the stored token", () => {
      setToken("test-token-123")
      expect(getToken()).toBe("test-token-123")
    })

    it("clears both token and user on clearToken", () => {
      setToken("test-token")
      setStoredUser({ id: "1", username: "admin", role: "admin" })
      clearToken()
      expect(getToken()).toBeNull()
      expect(getStoredUser()).toBeNull()
    })
  })

  describe("getStoredUser / setStoredUser", () => {
    it("returns null when no user is stored", () => {
      expect(getStoredUser()).toBeNull()
    })

    it("returns the stored user object", () => {
      const user: AuthUser = { id: "1", username: "test", role: "user" }
      setStoredUser(user)
      expect(getStoredUser()).toEqual(user)
    })
  })

  describe("isAuthenticated", () => {
    it("returns false when not authenticated", () => {
      expect(isAuthenticated()).toBe(false)
    })

    it("returns true when token is set", () => {
      setToken("any-token")
      expect(isAuthenticated()).toBe(true)
    })
  })

  describe("isAdmin", () => {
    it("returns false when no user stored", () => {
      expect(isAdmin()).toBe(false)
    })

    it("returns true for admin role", () => {
      setStoredUser({ id: "1", username: "admin", role: "admin" })
      expect(isAdmin()).toBe(true)
    })

    it("returns false for user role", () => {
      setStoredUser({ id: "2", username: "test", role: "user" })
      expect(isAdmin()).toBe(false)
    })
  })

  describe("authHeaders", () => {
    it("returns empty headers when not authenticated", () => {
      expect(authHeaders()).toEqual({})
    })

    it("injects Bearer token when authenticated", () => {
      setToken("my-jwt-token")
      const headers = authHeaders()
      expect(headers["Authorization"]).toBe("Bearer my-jwt-token")
    })

    it("merges with existing headers", () => {
      setToken("token")
      const headers = authHeaders({ "Content-Type": "application/json" })
      expect(headers["Authorization"]).toBe("Bearer token")
      expect(headers["Content-Type"]).toBe("application/json")
    })
  })
})
