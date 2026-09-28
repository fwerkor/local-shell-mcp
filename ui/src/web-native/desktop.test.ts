import { describe, expect, test } from "bun:test"
import {
  DesktopController,
  MAX_PENDING_DESKTOP_ACTIONS,
  SINGLE_CLICK_DELAY_MS,
  framePoint,
  wheelScrollAmount,
} from "./desktop"
import type { NativePageContext } from "./common"

describe("Native WebUI desktop coordinate mapping", () => {
  test("maps rendered image coordinates back to logical window pixels", () => {
    const rect = { left: 100, top: 50, right: 900, bottom: 500, width: 800, height: 450 }
    const bounds = { x: 1400, y: 200, width: 1600, height: 900 }

    expect(framePoint(100, 50, rect, bounds)).toEqual({ x: 0, y: 0 })
    expect(framePoint(500, 275, rect, bounds)).toEqual({ x: 800, y: 450 })
    expect(framePoint(899.9, 499.9, rect, bounds)).toEqual({ x: 1599, y: 899 })
  })

  test("rejects pointer positions outside the rendered frame", () => {
    const rect = { left: 10, top: 10, right: 110, bottom: 60, width: 100, height: 50 }
    const bounds = { x: 0, y: 0, width: 200, height: 100 }

    expect(framePoint(9, 20, rect, bounds)).toBeNull()
    expect(framePoint(110, 20, rect, bounds)).toBeNull()
    expect(framePoint(20, 60, rect, bounds)).toBeNull()
  })
})

describe("Native WebUI desktop click handling", () => {
  test("waits for the browser double-click window before dispatching a single click", () => {
    expect(SINGLE_CLICK_DELAY_MS).toBeGreaterThanOrEqual(500)
  })
})

describe("Native WebUI desktop window refresh", () => {
  test("immediately refreshes the new machine after an older request finishes", async () => {
    const calls: string[] = []
    const resolvers: Array<(value: unknown) => void> = []
    const context: NativePageContext = {
      api: {
        get: async (url: string) => {
          calls.push(url)
          return await new Promise<unknown>((resolve) => { resolvers.push(resolve) }) as never
        },
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller: any = new DesktopController(context)
    controller.renderSelectors = () => undefined
    controller.clearFrame = () => undefined
    controller.refreshFrame = async () => undefined
    controller.machine = "old"

    const first = controller.refreshWindows(false)
    expect(calls[0]).toContain("machine=old")

    controller.machine = "new"
    await controller.refreshWindows(true)
    expect(calls).toHaveLength(1)

    resolvers[0]?.({ windows: [], backend: "" })
    await first
    await Promise.resolve()

    expect(calls).toHaveLength(2)
    expect(calls[1]).toContain("machine=new")
    resolvers[1]?.({ windows: [], backend: "" })
    await Promise.resolve()
  })
})

describe("Native WebUI desktop Wayland capture", () => {
  test("does not auto-refresh focus-changing Wayland frames locally or remotely", async () => {
    const context: NativePageContext = {
      api: {
        get: async () => ({
          windows: [{ id: "window:1" }],
          backend: "linux-atspi",
          capabilities: { capture_requires_focus: true },
        }) as never,
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller: any = new DesktopController(context)
    controller.root = { querySelector: () => null }
    controller.renderSelectors = () => undefined
    controller.clearFrame = () => undefined
    let frames = 0
    controller.refreshFrame = async () => { frames += 1 }

    controller.machine = "local"
    await controller.refreshWindows(true)
    expect(controller.captureRequiresFocus).toBe(true)
    expect(frames).toBe(0)

    controller.machine = "node"
    await controller.refreshWindows(true)
    expect(controller.captureRequiresFocus).toBe(true)
    expect(frames).toBe(0)
  })
})

describe("Native WebUI desktop queued input", () => {
  test("bounds same-target input backlog", async () => {
    const sends: unknown[] = []
    let releaseFirst!: () => void
    const gate = new Promise<void>((resolve) => { releaseFirst = resolve })
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (_url: string, _method: string, body?: unknown) => {
          sends.push(body)
          if (sends.length === 1) await gate
          return {} as never
        },
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller: any = new DesktopController(context)
    controller.root = { querySelector: () => null }
    controller.machine = "node"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.refreshFrame = async () => undefined

    for (let index = 0; index < MAX_PENDING_DESKTOP_ACTIONS + 20; index += 1) {
      controller.queueAction({ type: "key", keys: ["A"] })
    }
    expect(controller.pendingActions).toBe(MAX_PENDING_DESKTOP_ACTIONS)
    await Promise.resolve()
    releaseFirst()
    await controller.actionQueue

    expect(sends).toHaveLength(MAX_PENDING_DESKTOP_ACTIONS)
    expect(controller.pendingActions).toBe(0)
  })

  test("refreshes once after the queued action batch drains", async () => {
    const sends: unknown[] = []
    let releaseFirst!: () => void
    const gate = new Promise<void>((resolve) => { releaseFirst = resolve })
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (_url: string, _method: string, body?: unknown) => {
          sends.push(body)
          if (sends.length === 1) await gate
          return {} as never
        },
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller: any = new DesktopController(context)
    controller.root = { querySelector: () => null }
    controller.machine = "node"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    let frames = 0
    controller.refreshFrame = async () => { frames += 1 }

    controller.queueAction({ type: "click", x: 1, y: 1 })
    await Promise.resolve()
    controller.queueAction({ type: "click", x: 2, y: 2 })
    releaseFirst()
    await controller.actionQueue

    expect(sends).toHaveLength(2)
    expect(frames).toBe(1)
    expect(controller.pendingActions).toBe(0)
  })

  test("invalidates a pre-action frame request before requesting the final frame", async () => {
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async () => ({} as never),
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller: any = new DesktopController(context)
    controller.root = { querySelector: () => null }
    controller.machine = "node"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.framePromise = new Promise<void>(() => undefined)
    controller.frameRequestKey = "node\0window:1"
    let aborts = 0
    controller.frameAbort = { abort: () => { aborts += 1 } }
    let frames = 0
    controller.refreshFrame = async () => { frames += 1 }

    controller.queueAction({ type: "click", x: 1, y: 1 })
    await controller.actionQueue

    expect(aborts).toBe(1)
    expect(frames).toBe(1)
  })

  test("invalidates later queued actions after a stale-frame rejection", async () => {
    const sends: unknown[] = []
    let releaseFirst!: () => void
    const gate = new Promise<void>((resolve) => { releaseFirst = resolve })
    const refreshes: boolean[] = []

    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (_url: string, _method: string, body?: unknown) => {
          sends.push(body)
          if (sends.length === 1) {
            await gate
            throw new Error("Target window moved or resized since the displayed frame")
          }
          return {} as never
        },
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller: any = new DesktopController(context)
    controller.root = { querySelector: () => null }
    controller.machine = "node"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.refreshFrame = async () => undefined
    controller.refreshWindows = async (force: boolean) => { refreshes.push(force) }

    controller.queueAction({ type: "click", x: 1, y: 1 })
    await Promise.resolve()
    controller.queueAction({ type: "click", x: 2, y: 2 })
    releaseFirst()
    await controller.actionQueue

    expect(sends).toHaveLength(1)
    expect(refreshes).toEqual([true])
  })

  test("drops queued actions after the target changes", async () => {
    const sends: unknown[] = []
    let releaseFirst!: () => void
    const first = new Promise<void>((resolve) => { releaseFirst = resolve })

    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (_url: string, _method: string, body?: unknown) => {
          sends.push(body)
          if (sends.length === 1) await first
          return {} as never
        },
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller: any = new DesktopController(context)
    controller.root = { querySelector: () => null }
    controller.machine = "old"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.refreshFrame = async () => undefined

    controller.queueAction({ type: "click", x: 1, y: 1 })
    await Promise.resolve()
    controller.queueAction({ type: "click", x: 2, y: 2 })

    controller.machine = "new"
    controller.selectedWindowId = "window:2"
    controller.invalidateActionTarget()

    releaseFirst()
    await controller.actionQueue

    expect(sends).toHaveLength(1)
    expect(sends[0]).toEqual({
      machine: "old",
      window_id: "window:1",
      bounds: { x: 0, y: 0, width: 100, height: 100 },
      actions: [{ type: "click", x: 1, y: 1 }],
    })
  })
})

describe("Native WebUI desktop frame replacement", () => {
  test("publishes new geometry only after the replacement image decodes", async () => {
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller: any = new DesktopController(context)
    const visibleImage: any = { src: "blob:old", hidden: false }
    controller.root = {
      querySelector: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? visibleImage : null
      ),
    }
    controller.machine = "local"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.frameUrl = "blob:old"
    controller.frameRequestKey = "local\0window:1"
    controller.frameEpoch = 0

    let releaseDecode!: () => void
    const decodeGate = new Promise<void>((resolve) => { releaseDecode = resolve })
    controller.decodeFrame = async () => { await decodeGate }

    const originalFetch = globalThis.fetch
    const originalCreateObjectURL = URL.createObjectURL
    const originalRevokeObjectURL = URL.revokeObjectURL
    globalThis.fetch = (async () => new Response(new Blob(["frame"]), {
      status: 200,
      headers: {
        "X-LSM-GUI-Window-X": "0",
        "X-LSM-GUI-Window-Y": "0",
        "X-LSM-GUI-Window-Width": "200",
        "X-LSM-GUI-Window-Height": "150",
      },
    })) as unknown as typeof fetch
    URL.createObjectURL = () => "blob:new"
    URL.revokeObjectURL = () => undefined

    try {
      const task = controller.loadFrame("local\0window:1", new AbortController())
      await Promise.resolve()
      await Promise.resolve()
      expect(controller.frameBounds).toEqual({ x: 0, y: 0, width: 100, height: 100 })
      expect(visibleImage.src).toBe("blob:old")

      releaseDecode()
      await task
      expect(controller.frameBounds).toEqual({ x: 0, y: 0, width: 200, height: 150 })
      expect(visibleImage.src).toBe("blob:new")
    } finally {
      globalThis.fetch = originalFetch
      URL.createObjectURL = originalCreateObjectURL
      URL.revokeObjectURL = originalRevokeObjectURL
    }
  })
})

describe("Native WebUI desktop shortcut encoding", () => {
  test("preserves Ctrl+Plus and Ctrl+Space as unambiguous key arrays", () => {
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => null,
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
    }
    const controller: any = new DesktopController(context)
    const stage = { contains: () => true }
    controller.root = { querySelector: () => stage }
    const queued: unknown[] = []
    controller.queueAction = (action: unknown) => { queued.push(action) }

    const target = { closest: () => null }
    const makeEvent = (
      key: string,
      code: string,
      {
        ctrl = false,
        meta = false,
        shift = false,
      }: { ctrl?: boolean; meta?: boolean; shift?: boolean },
    ) => ({
      key,
      code,
      ctrlKey: ctrl,
      metaKey: meta,
      altKey: false,
      shiftKey: shift,
      target,
      preventDefault: () => undefined,
    })

    controller.onKeyDown(makeEvent("+", "Equal", { ctrl: true, shift: true }))
    controller.onKeyDown(makeEvent(" ", "Space", { ctrl: true }))
    controller.onKeyDown(makeEvent("!", "Digit1", { meta: true, shift: true }))
    controller.onKeyDown(makeEvent("{", "BracketLeft", { meta: true, shift: true }))
    controller.onKeyDown(makeEvent("?", "Slash", { meta: true, shift: true }))

    expect(queued).toEqual([
      { type: "key", keys: ["CTRL", "SHIFT", "="] },
      { type: "key", keys: ["CTRL", "SPACE"] },
      { type: "key", keys: ["META", "SHIFT", "1"] },
      { type: "key", keys: ["META", "SHIFT", "["] },
      { type: "key", keys: ["META", "SHIFT", "/"] },
    ])
  })
})

describe("Native WebUI desktop wheel mapping", () => {
  test("keeps zero a no-op and maps browser-down to native-down", () => {
    expect(wheelScrollAmount(0)).toBe(0)
    expect(wheelScrollAmount(10)).toBe(-1)
    expect(wheelScrollAmount(-10)).toBe(1)
    expect(wheelScrollAmount(10000)).toBe(-12)
  })
})
