import { describe, expect, test } from "bun:test"
import { fileBreadcrumbRows, fileParentPath, fileTreeEntries, fileTreeId, FilesController } from "./files"

describe("Native Files browser path isolation", () => {
  test("keeps UNC and Windows drive roots navigable", () => {
    expect(fileBreadcrumbRows("\\\\server\\share\\dir")).toEqual([
      { label: "\\\\server\\share", path: "\\\\server\\share" },
      { label: "dir", path: "\\\\server\\share\\dir" },
    ])
    expect(fileBreadcrumbRows("C:\\work\\repo")[0]).toEqual({ label: "C:", path: "C:\\" })
    expect(fileBreadcrumbRows("/srv/app")[0]).toEqual({ label: "/", path: "/" })
    expect(fileParentPath("/")).toBe("/")
    expect(fileParentPath("C:\\")).toBe("C:\\")
    expect(fileParentPath("\\\\server\\share")).toBe("\\\\server\\share")
    expect(fileParentPath("/srv/app")).toBe("/srv")
    expect(fileParentPath("subdir")).toBe(".")
  })

  test("uses browser-only ids independent of remote platform", () => {
    expect(fileTreeId("/", "A B#? %.txt")).toBe("/A%20B%23%3F%20%25.txt")
    expect(fileTreeId("/Models", "weights.safetensors")).toBe("/Models/weights.safetensors")
    const entries = [
      { name: "data", path: "C:\\work\\data", type: "dir", hidden: false, modified: 20 },
      { name: "file.bin", path: "C:\\work\\file.bin", type: "file", size: 42, modified: 5 },
      { name: ".env", path: "C:\\work\\.env", type: "file", hidden: true },
    ]
    expect(fileTreeEntries(entries, "/", false).map((x) => x.id)).toEqual(["/data", "/file.bin"])
    expect(fileTreeEntries(entries, "/", true)).toHaveLength(3)
    expect(fileTreeEntries(entries, "/", true)[0]).toMatchObject({ type: "folder", lazy: true, name: "data" })
  })
})

describe("Native Files async scope", () => {
  test("preserves the navigated folder across refreshes", () => {
    const location = { value: "" }
    const controller: any = new FilesController({ notify: () => {} } as any)
    controller.root = { querySelector: () => location }
    controller.paths = new Map([["/", "."], ["/nested", "/work/nested"]])
    controller.selectFolder("/nested")
    expect(controller.location).toBe("/work/nested")
    expect(controller.selectedFolder).toBe("/nested")
    expect(location.value).toBe("/work/nested")
  })

  test("refreshes an open folder without rebuilding the explorer tree", async () => {
    const requests: string[] = []
    const provided: object[] = []
    const controller: any = new FilesController({
      machines: () => [{ name: "local", status: "online" }],
      api: { get: async (path: string) => { requests.push(path); return { entries: [] } } },
      notify: () => {},
    } as any)
    controller.machine = "local"
    controller.renderedMachine = "local"
    controller.generation = 3
    controller.selectedFolder = "/nested"
    controller.location = "/work/nested"
    controller.paths = new Map([["/", "/work"], ["/nested", "/work/nested"]])
    controller.api = { exec: async (_: string, args: object) => { provided.push(args) } }
    controller.renderExplorer = () => { throw new Error("explorer should not remount") }
    await controller.refresh()
    expect(controller.generation).toBe(3)
    expect(requests[0]).toContain("path=%2Fwork%2Fnested")
    expect(provided).toHaveLength(1)
  })

  test("recovers when the selected remote disappears", async () => {
    const requests: string[] = []
    const controller: any = new FilesController({
      machines: () => [{ name: "local", status: "online" }],
      api: { get: async (path: string) => { requests.push(path); return { entries: [] } } },
      notify: () => {},
    } as any)
    controller.root = { querySelector: () => ({ value: "", setAttribute: () => {}, removeAttribute: () => {} }) }
    controller.machine = "removed-worker"
    controller.location = "/old-remote-path"
    controller.renderExplorer = () => {}
    await controller.refresh()
    expect(controller.machine).toBe("local")
    expect(controller.location).toBe(".")
    expect(requests[0]).toContain("machine=local")
    expect(requests[0]).not.toContain("old-remote-path")
  })

  test("queues separate SVAR upload callbacks instead of dropping files", async () => {
    const originalFetch = globalThis.fetch
    const uploads: string[] = []
    const notices: string[] = []
    const controller: any = new FilesController({
      apiPrefix: "/api/ui", accessToken: () => "token", notify: (msg: string) => notices.push(msg),
    } as any)
    controller.machine = "worker-a"
    controller.generation = 1
    controller.root = { querySelector: () => ({ hidden: true, textContent: "" }) }
    controller.reloadCurrent = async () => {}
    globalThis.fetch = (async (url: string) => {
      uploads.push(String(url))
      return Response.json({ ok: true })
    }) as typeof fetch
    try {
      await Promise.all([
        controller.uploadFiles([new File(["a"], "one.txt")], "/data"),
        controller.uploadFiles([new File(["b"], "two.txt")], "/data"),
      ])
      expect(uploads).toHaveLength(2)
      expect(uploads[0]).toContain("one.txt")
      expect(uploads[1]).toContain("two.txt")
      expect(notices).not.toContain("A file upload is already running")
    } finally { globalThis.fetch = originalFetch }
  })

  test("ignores late lazy directory results after machine change", async () => {
    let resolve!: (value: unknown) => void
    const requested: string[] = []
    const controller: any = new FilesController({
      api: { get: (path: string) => { requested.push(path); return new Promise((r) => { resolve = r }) } },
      notify: () => {},
    } as any)
    controller.machine = "alpha"
    controller.paths = new Map([["/data", "/srv/data"]])
    controller.generation = 1
    controller.api = { exec: () => { throw new Error("should not render old machine data") } }
    const loading = controller.loadFolder("/data", 1)
    controller.machine = "beta"
    controller.generation = 2
    resolve({ entries: [{ name: "secret", path: "/srv/data/secret", type: "file" }] })
    await loading
    expect(requested[0]).toContain("machine=alpha")
    expect(controller.paths.has("/data/secret")).toBe(false)
  })

  test("batches file deletes using selected machine and original paths", async () => {
    const writes: unknown[] = []
    const controller: any = new FilesController({
      api: { send: async (endpoint: string, method: string, data: object) => { writes.push({ endpoint, ...data }) } },
      notify: () => {},
    } as any)
    controller.machine = "worker-a"
    controller.paths = new Map([["/a", "C:\\dir\\a"], ["/b", "C:\\dir\\b"]])
    controller.generation = 1
    controller.reloadCurrent = async () => {}
    await controller.relocate(["/a", "/b"], "/", "copy", 1)
    expect(writes).toHaveLength(0)
    controller.paths.set("/", "C:\\new")
    await controller.relocate(["/a", "/b"], "/", "copy", 1)
    expect(writes).toEqual([
      { endpoint: "/files/copy", machine: "worker-a", path: "C:\\dir\\a", destination: "C:\\new\\a" },
      { endpoint: "/files/copy", machine: "worker-a", path: "C:\\dir\\b", destination: "C:\\new\\b" },
    ])
  })
})
