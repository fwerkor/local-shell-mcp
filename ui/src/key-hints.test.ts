import { describe, expect, test } from "bun:test"
import { layoutKeyHints } from "./key-hints"

describe("layoutKeyHints", () => {
  test("keeps actions and disabled state while compacting labels", () => {
    const action = () => undefined
    const layout = layoutKeyHints([
      { key: "n", label: "new terminal", onPress: action },
      { key: "d", label: "delete", onPress: action, disabled: true },
    ], 70)

    expect(layout.items).toEqual([
      { key: "n", label: "new ter", onPress: action },
      { key: "d", label: "delete", onPress: action, disabled: true },
    ])
    expect(layout.clipped).toBe(false)
  })

  test("falls back to key-only buttons before clipping actions", () => {
    const layout = layoutKeyHints([
      { key: "n", label: "new terminal", onPress: () => undefined },
      { key: "w", label: "kill terminal", onPress: () => undefined },
      { key: "a", label: "toggle audit", onPress: () => undefined },
      { key: "r", label: "refresh output", onPress: () => undefined },
    ], 30)

    expect(layout.keysOnly).toBe(true)
    expect(layout.items.map((item) => item.key)).toEqual(["n", "w", "a", "r"])
    expect(layout.clipped).toBe(false)
  })

  test("shows keys only on narrow terminals and clips whole buttons", () => {
    const layout = layoutKeyHints([
      { key: "Alt+Left", label: "previous terminal", onPress: () => undefined },
      { key: "Alt+Right", label: "next terminal", onPress: () => undefined },
    ], 20)

    expect(layout.keysOnly).toBe(true)
    expect(layout.items.map((item) => [item.key, item.label])).toEqual([["Alt+Left", ""]])
    expect(layout.clipped).toBe(true)
  })
})
