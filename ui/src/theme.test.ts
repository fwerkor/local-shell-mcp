import { describe, expect, test } from "bun:test"
import { parseColor } from "@opentui/core"
import { canvasBackground, screenTheme, theme } from "./theme"

describe("TUI theme", () => {
  test("gives every top-level screen a distinct identity", () => {
    const screens = Object.values(screenTheme)

    expect(new Set(screens.map(({ accent }) => accent)).size).toBe(screens.length)
    expect(new Set(screens.map(({ selected }) => selected)).size).toBe(screens.length)
    expect(new Set(screens.map(({ panel }) => panel)).size).toBe(screens.length)
  })

  test("keeps semantic colors separate from the neutral chrome", () => {
    const semantic = [theme.red, theme.green, theme.yellow, theme.blue, theme.magenta, theme.cyan]
    const neutral = [theme.bg, theme.panel, theme.panelAlt, theme.text, theme.muted, theme.faint]

    for (const color of semantic) expect(neutral).not.toContain(color)
  })

  test("uses the terminal default background only inside the WebUI", () => {
    expect(parseColor(canvasBackground("web")).a).toBe(0)
    expect(canvasBackground("tui")).toBe(theme.bg)
  })
})
