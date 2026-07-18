import { describe, expect, test } from "bun:test"
import { DOUBLE_CLICK_WINDOW_MS, isDoubleClick, pathBreadcrumbs } from "./file-navigation"

describe("file pointer navigation", () => {
  test("requires two presses on the same item within the double-click window", () => {
    const first = { target: "src", at: 1_000 }
    expect(isDoubleClick(first, "src", 1_000 + DOUBLE_CLICK_WINDOW_MS)).toBe(true)
    expect(isDoubleClick(first, "tests", 1_100)).toBe(false)
    expect(isDoubleClick(first, "src", 1_000 + DOUBLE_CLICK_WINDOW_MS + 1)).toBe(false)
    expect(isDoubleClick(first, "src", 999)).toBe(false)
  })
})

describe("file path breadcrumbs", () => {
  test("builds workspace-relative breadcrumbs", () => {
    expect(pathBreadcrumbs("src/local_shell_mcp/ui_static")).toEqual([
      { label: ".", path: "." },
      { label: "src", path: "src" },
      { label: "local_shell_mcp", path: "src/local_shell_mcp" },
      { label: "ui_static", path: "src/local_shell_mcp/ui_static" },
    ])
  })

  test("builds absolute POSIX breadcrumbs", () => {
    expect(pathBreadcrumbs("/var/lib/lsm")).toEqual([
      { label: "/", path: "/" },
      { label: "var", path: "/var" },
      { label: "lib", path: "/var/lib" },
      { label: "lsm", path: "/var/lib/lsm" },
    ])
  })

  test("builds Windows drive and UNC breadcrumbs", () => {
    expect(pathBreadcrumbs("C:\\Users\\agent")).toEqual([
      { label: "C:\\", path: "C:\\" },
      { label: "Users", path: "C:\\Users" },
      { label: "agent", path: "C:\\Users\\agent" },
    ])
    expect(pathBreadcrumbs("\\\\server\\share\\folder")).toEqual([
      { label: "\\\\server\\share", path: "\\\\server\\share" },
      { label: "folder", path: "\\\\server\\share\\folder" },
    ])
  })
})
