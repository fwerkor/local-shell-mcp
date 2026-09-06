import { describe, expect, test } from "bun:test"
import { fileBreadcrumbRows, filterAndSortFileEntries } from "./files"

describe("Native WebUI file breadcrumbs", () => {
  test("preserves Windows UNC share roots", () => {
    expect(fileBreadcrumbRows("\\\\server\\share\\dir\\file")).toEqual([
      { label: "\\\\server\\share", path: "\\\\server\\share" },
      { label: "dir", path: "\\\\server\\share\\dir" },
      { label: "file", path: "\\\\server\\share\\dir\\file" },
    ])
  })

  test("preserves drive and POSIX roots", () => {
    expect(fileBreadcrumbRows("C:\\work\\repo")[0]).toEqual({ label: "C:", path: "C:\\" })
    expect(fileBreadcrumbRows("/srv/app")[0]).toEqual({ label: "/", path: "/" })
  })

  test("filters case-insensitively and keeps directories before files", () => {
    const entries = [
      { path: "src/app.ts", name: "app.ts", type: "file", size: 20, modified: 3 },
      { path: "src/App", name: "App", type: "dir", size: 0, modified: 1 },
      { path: "notes.md", name: "notes.md", type: "file", size: 2, modified: 2 },
    ]
    expect(filterAndSortFileEntries(entries, "APP", "name", "asc").map((entry) => entry.path)).toEqual(["src/App", "src/app.ts"])
  })

  test("sorts file metadata in either direction", () => {
    const entries = [
      { path: "large", name: "large", type: "file", size: 20, modified: 1 },
      { path: "small", name: "small", type: "file", size: 2, modified: 3 },
    ]
    expect(filterAndSortFileEntries(entries, "", "size", "asc").map((entry) => entry.name)).toEqual(["small", "large"])
    expect(filterAndSortFileEntries(entries, "", "modified", "desc").map((entry) => entry.name)).toEqual(["small", "large"])
  })
})
