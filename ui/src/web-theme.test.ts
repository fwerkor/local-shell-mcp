import { describe, expect, test } from "bun:test"
import { nextThemePreference, parseThemePreference, resolvedTheme } from "./web-theme"

describe("WebUI color theme", () => {
  test("supports explicit dark and light overrides and system preference", () => {
    expect(resolvedTheme("system", true)).toBe("dark")
    expect(resolvedTheme("system", false)).toBe("light")
    expect(resolvedTheme("light", true)).toBe("light")
    expect(resolvedTheme("dark", false)).toBe("dark")
  })
  test("falls back to system and cycles through user choices", () => {
    expect(parseThemePreference("invalid")).toBe("system")
    expect(parseThemePreference(null)).toBe("system")
    expect(parseThemePreference("dark")).toBe("dark")
    expect(nextThemePreference("system")).toBe("light")
    expect(nextThemePreference("light")).toBe("dark")
    expect(nextThemePreference("dark")).toBe("system")
  })
})
