import { describe, expect, test } from "bun:test"
import { parseKeypress } from "@opentui/core"
import { browserShortcutSequence } from "./keyboard"

function shortcut(key: string) {
  return browserShortcutSequence({ key, altKey: true, ctrlKey: false, metaKey: false })
}

describe("browserShortcutSequence", () => {
  test("forwards Escape globally and provides Ctrl+[ as a fallback", () => {
    expect(browserShortcutSequence({ key: "Escape", altKey: false, ctrlKey: false, metaKey: false })).toBe("\u001b")
    expect(browserShortcutSequence({ key: "[", altKey: false, ctrlKey: true, metaKey: false })).toBe("\u001b")
  })

  test("maps category shortcuts to the TUI function keys", () => {
    expect(shortcut("1")).toBe("\u001bOQ")
    expect(shortcut("5")).toBe("\u001b[17~")
  })

  test("encodes terminal actions as reliable Alt key events", () => {
    for (const [key, name] of [["n", "n"], ["w", "w"], ["a", "a"], ["r", "r"], ["[", "["], ["]", "]"]] as const) {
      const sequence = shortcut(key)
      expect(sequence).toBeDefined()
      const parsed = parseKeypress(Buffer.from(sequence!), { useKittyKeyboard: true })
      expect(parsed?.name).toBe(name)
      expect(parsed?.option).toBe(true)
    }
  })

  test("encodes terminal switching without triggering browser history", () => {
    const left = parseKeypress(Buffer.from(shortcut("ArrowLeft")!), { useKittyKeyboard: true })
    const right = parseKeypress(Buffer.from(shortcut("ArrowRight")!), { useKittyKeyboard: true })
    expect(left?.name).toBe("left")
    expect(left?.option).toBe(true)
    expect(right?.name).toBe("right")
    expect(right?.option).toBe(true)
  })

  test("ignores non-Alt and mixed modifier shortcuts", () => {
    expect(browserShortcutSequence({ key: "n", altKey: false, ctrlKey: false, metaKey: false })).toBeUndefined()
    expect(browserShortcutSequence({ key: "n", altKey: true, ctrlKey: true, metaKey: false })).toBeUndefined()
    expect(browserShortcutSequence({ key: "n", altKey: true, ctrlKey: false, metaKey: true })).toBeUndefined()
    expect(browserShortcutSequence({ key: "Escape", altKey: true, ctrlKey: false, metaKey: false })).toBeUndefined()
  })
})
