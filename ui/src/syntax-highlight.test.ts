import { describe, expect, test } from "bun:test"
import { highlightModeForFilename, tokenizeHighlightedText, tokenizeJson } from "./syntax-highlight"

function rendered(tokens: ReturnType<typeof tokenizeHighlightedText>): string {
  return tokens.map((token) => token.text).join("")
}

describe("syntax highlighting", () => {
  test("distinguishes JSON keys from scalar values without changing content", () => {
    const source = '{\n  "name": "lsm",\n  "count": 3,\n  "ok": true\n}'
    const tokens = tokenizeJson(source)

    expect(rendered(tokens)).toBe(source)
    expect(tokens.some((token) => token.kind === "key" && token.text === '"name"')).toBe(true)
    expect(tokens.some((token) => token.kind === "string" && token.text === '"lsm"')).toBe(true)
    expect(tokens.some((token) => token.kind === "number" && token.text === "3")).toBe(true)
    expect(tokens.some((token) => token.kind === "literal" && token.text === "true")).toBe(true)
  })

  test("uses lightweight extension-based modes", () => {
    expect(highlightModeForFilename("worker.ts")).toBe("code")
    expect(highlightModeForFilename("config.yaml")).toBe("config")
    expect(highlightModeForFilename("README.md")).toBe("markdown")
    expect(highlightModeForFilename("notes.txt")).toBe("plain")
  })

  test("preserves source text for code and config previews", () => {
    const code = "const answer = 42 // result\n"
    const config = "enabled: true\nname: lsm\n"

    expect(rendered(tokenizeHighlightedText(code, "main.ts"))).toBe(code)
    expect(rendered(tokenizeHighlightedText(config, "config.yaml"))).toBe(config)
  })
})
