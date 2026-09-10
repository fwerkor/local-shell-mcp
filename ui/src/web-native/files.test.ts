import { describe, expect, test } from "bun:test"
import { FilesController, fileBreadcrumbRows, filterAndSortFileEntries } from "./files"

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

describe("Native WebUI file actions", () => {
  test("keeps the Workspace shortcut at the logical workspace root", () => {
    const navigated: string[] = []
    const controller = {
      machine: "local",
      machines: () => [{ name: "local", status: "online", workdir: "/workspace" }],
      navigate: (path: string) => navigated.push(path),
    }
    const event = {
      target: {
        closest: (selector: string) => selector === "[data-action]" ? { dataset: { action: "home-location" } } : null,
      },
    }

    ;(FilesController.prototype as any).onClick.call(controller, event)

    expect(navigated).toEqual(["."])
  })

  test("keeps every file in an upload batch on its initial machine and path", async () => {
    const writes: Array<{ machine: string; path: string }> = []
    const controller: any = {
      machine: "local",
      path: "uploads",
      context: {
        api: {
          send: async (_endpoint: string, _method: string, body: { machine: string; path: string }) => {
            writes.push({ machine: body.machine, path: body.path })
            controller.machine = "remote"
            controller.path = "elsewhere"
          },
        },
        notify: () => {},
      },
      refresh: async () => {},
    }
    const files = ["first.txt", "second.txt"].map((name) => ({
      name,
      arrayBuffer: async () => Uint8Array.from([1, 2, 3]).buffer,
    }))

    await (FilesController.prototype as any).upload.call(controller, files)

    expect(writes).toEqual([
      { machine: "local", path: "uploads/first.txt" },
      { machine: "local", path: "uploads/second.txt" },
    ])
  })
})
