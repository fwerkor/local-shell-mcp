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


describe("Native WebUI file performance", () => {
  test("reuses the derived directory entries until payload or filters change", () => {
    const controller: any = new FilesController({} as any)
    controller.payload = {
      machine: "local",
      path: ".",
      parent: ".",
      entries: [
        { path: "b", name: "b", type: "file", size: 2, modified: 2 },
        { path: "a", name: "a", type: "file", size: 1, modified: 1 },
      ],
      parent_entries: [],
    }

    const first = controller.entries()
    const second = controller.entries()
    expect(second).toBe(first)

    controller.query = "a"
    const filtered = controller.entries()
    expect(filtered).not.toBe(first)
    expect(filtered.map((entry: { path: string }) => entry.path)).toEqual(["a"])
  })

  test("does not refetch an unchanged selected preview", async () => {
    let requests = 0
    const controller: any = new FilesController({
      api: {
        get: async () => { requests += 1; return { kind: "text", content: "hello" } },
      },
    } as any)
    controller.machine = "local"
    controller.payload = {
      machine: "local",
      path: ".",
      parent: ".",
      entries: [{ path: "a.txt", name: "a.txt", type: "file", size: 5, modified: 1 }],
      parent_entries: [],
    }
    controller.selectedPath = "a.txt"
    controller.root = { querySelector: () => null }
    controller.renderPreview = () => undefined

    await controller.loadPreview()
    await controller.loadPreview()

    expect(requests).toBe(1)
  })

  test("coalesces a forced preview refresh with the same request already in flight", async () => {
    let requests = 0
    let resolvePreview!: (value: unknown) => void
    const controller: any = new FilesController({
      api: {
        get: async () => {
          requests += 1
          return new Promise((resolve) => { resolvePreview = resolve })
        },
      },
    } as any)
    controller.machine = "local"
    controller.payload = {
      machine: "local", path: ".", parent: ".",
      entries: [{ path: "a.txt", name: "a.txt", type: "file", size: 5, modified: 1 }],
      parent_entries: [],
    }
    controller.selectedPath = "a.txt"
    controller.root = { querySelector: () => null }
    controller.renderPreview = () => undefined

    const first = controller.loadPreview()
    const forced = controller.loadPreview(true)
    expect(requests).toBe(1)
    resolvePreview({ kind: "text", content: "hello" })
    await Promise.all([first, forced])
    expect(requests).toBe(1)
  })

  test("changes file selection without rebuilding the directory table", () => {
    const controller: any = new FilesController({} as any)
    controller.selectedPath = "a"
    controller.preview = { kind: "text", content: "old" }
    let selectionUpdates = 0
    let directoryRenders = 0
    controller.updateDirectorySelection = () => { selectionUpdates += 1 }
    controller.renderDirectory = () => { directoryRenders += 1 }
    controller.focusEntry = () => undefined
    controller.loadPreview = async () => undefined

    controller.select("b")

    expect(controller.selectedPath).toBe("b")
    expect(selectionUpdates).toBe(1)
    expect(directoryRenders).toBe(0)
  })
})
