import { describe, expect, test } from "bun:test"
import { libreChatLoginAction } from "./librechat"

describe("Full-page LSM workspace handoff", () => {
  test("posts tickets directly to the configured HTTPS chat origin", () => {
    expect(libreChatLoginAction("https://chat.example.org/control/overview"))
      .toBe("https://chat.example.org/api/auth/lsm")
  })

  test("allows HTTP loopback solely for isolated development", () => {
    expect(libreChatLoginAction("http://localhost:3080"))
      .toBe("http://localhost:3080/api/auth/lsm")
    expect(libreChatLoginAction("http://127.0.0.1:3080"))
      .toBe("http://127.0.0.1:3080/api/auth/lsm")
  })

  test("rejects insecure remote origins and embedded credentials", () => {
    for (const url of [
      "http://chat.example.org", "http://10.1.1.1:3080",
      "https://user:password@chat.example.org", "not-a-url",
    ]) expect(() => libreChatLoginAction(url)).toThrow()
  })

  test("uses the top-level login rather than an iframe", async () => {
    const source = await Bun.file(new URL("./librechat.ts", import.meta.url)).text()
    expect(source).toContain('form.target = "_top"')
    expect(source).not.toContain("<iframe")
    expect(source).not.toContain("postMessage")
  })
})
