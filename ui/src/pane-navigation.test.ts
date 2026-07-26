import { describe, expect, test } from "bun:test"
import type { ScrollBoxRenderable } from "@opentui/core"
import { cyclePane, scrollPaneForKey } from "./pane-navigation"

describe("pane navigation", () => {
  test("cycles in both directions", () => {
    const panes = ["list", "output", "input"] as const
    expect(cyclePane(panes, "list", 1)).toBe("output")
    expect(cyclePane(panes, "list", -1)).toBe("input")
    expect(cyclePane(panes, "input", 1)).toBe("list")
  })

  test("maps navigation keys to imperative scrolling", () => {
    const calls: Array<[string, number, string?]> = []
    const pane = {
      scrollHeight: 42,
      scrollBy(delta: number, unit?: string) {
        calls.push(["by", delta, unit])
      },
      scrollTo(position: number) {
        calls.push(["to", position])
      },
    } as unknown as ScrollBoxRenderable

    expect(scrollPaneForKey(pane, { name: "j" })).toBe(true)
    expect(scrollPaneForKey(pane, { name: "pageup" })).toBe(true)
    expect(scrollPaneForKey(pane, { name: "home" })).toBe(true)
    expect(scrollPaneForKey(pane, { name: "end" })).toBe(true)
    expect(scrollPaneForKey(pane, { name: "x" })).toBe(false)
    expect(calls).toEqual([
      ["by", 1, undefined],
      ["by", -0.8, "viewport"],
      ["to", 0, undefined],
      ["to", 42, undefined],
    ])
  })
})
