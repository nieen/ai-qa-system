import { describe, it, expect, vi, beforeEach } from "vitest"
import { cn } from "@/lib/utils"

describe("utils", () => {
  describe("cn", () => {
    it("merges class names", () => {
      expect(cn("foo", "bar")).toBe("foo bar")
    })

    it("handles conditional classes", () => {
      expect(cn("base", false && "hidden", true && "visible")).toBe("base visible")
    })

    it("resolves tailwind conflicts (later wins)", () => {
      expect(cn("px-4", "px-2")).toBe("px-2")
    })

    it("handles empty inputs", () => {
      expect(cn()).toBe("")
    })
  })
})
