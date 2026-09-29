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

  test("does not turn click detail 3 into a second native double-click", () => {
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
    const image = {
      hidden: false,
      getBoundingClientRect: () => ({
        left: 0,
        top: 0,
        right: 100,
        bottom: 100,
        width: 100,
        height: 100,
      }),
    }
    controller.root = {
      querySelector: (selector: string) => (
        selector === "[data-role=desktop-frame]"
          ? image
          : selector === "[data-role=desktop-stage]"
            ? { focus: () => undefined }
            : null
      ),
    }
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.frameObservationId = "obs-1"
    controller.frameInputEnabled = true
    const actions: unknown[] = []
    controller.queueAction = (action: unknown) => { actions.push(action) }
    const target = {
      closest: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }

    controller.onClick({ target, button: 0, detail: 2, clientX: 10, clientY: 10 })
    controller.onClick({ target, button: 0, detail: 3, clientX: 10, clientY: 10 })

    expect(actions).toEqual([{ type: "double_click", x: 10, y: 10 }])
  })

  test("keeps a delayed single click bound to the frame that was clicked", async () => {
    const previousWindow = (globalThis as any).window
    ;(globalThis as any).window = globalThis
    const sends: any[] = []
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (_url: string, _method: string, body?: unknown) => {
          sends.push(body)
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
    const image: any = {
      hidden: false,
      getBoundingClientRect: () => ({
        left: 0,
        top: 0,
        right: 100,
        bottom: 100,
        width: 100,
        height: 100,
      }),
    }
    const stage = { focus: () => undefined }
    controller.root = {
      querySelector: (selector: string) => (
        selector === "[data-role=desktop-frame]"
          ? image
          : selector === "[data-role=desktop-stage]"
            ? stage
            : null
      ),
    }
    controller.machine = "node"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.frameObservationId = "obs-old"
    controller.frameInputEnabled = true
    controller.refreshFrame = async () => undefined
    const target = {
      closest: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }

    try {
      controller.onClick({
        target,
        button: 0,
        detail: 1,
        clientX: 10,
        clientY: 10,
      })
      controller.frameObservationId = "obs-new"
      controller.frameInputEnabled = true
      await new Promise((resolve) => setTimeout(resolve, SINGLE_CLICK_DELAY_MS + 25))
      await controller.actionQueue

      expect(sends).toHaveLength(1)
      expect(sends[0].observation_id).toBe("obs-old")
    } finally {
      if (previousWindow === undefined) delete (globalThis as any).window
      else (globalThis as any).window = previousWindow
    }
  })

  test("keeps coalesced wheel input bound to its source frame", async () => {
    const previousWindow = (globalThis as any).window
    ;(globalThis as any).window = globalThis
    const sends: any[] = []
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (_url: string, _method: string, body?: unknown) => {
          sends.push(body)
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
    const image: any = {
      hidden: false,
      getBoundingClientRect: () => ({
        left: 0,
        top: 0,
        right: 100,
        bottom: 100,
        width: 100,
        height: 100,
      }),
    }
    controller.root = {
      querySelector: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }
    controller.machine = "node"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.frameObservationId = "obs-wheel"
    controller.frameInputEnabled = true
    controller.refreshFrame = async () => undefined
    const target = {
      closest: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }

    try {
      controller.onWheel({
        target,
        deltaY: 120,
        clientX: 20,
        clientY: 20,
        preventDefault: () => undefined,
      })
      controller.frameObservationId = "obs-new"
      controller.frameInputEnabled = true
      await new Promise((resolve) => setTimeout(resolve, 80))
      await controller.actionQueue

      expect(sends).toHaveLength(1)
      expect(sends[0].observation_id).toBe("obs-wheel")
    } finally {
      if (previousWindow === undefined) delete (globalThis as any).window
      else (globalThis as any).window = previousWindow
    }
  })

  test("drops a drag when the frame changes mid-gesture", async () => {
    const sends: any[] = []
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (_url: string, _method: string, body?: unknown) => {
          sends.push(body)
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
    const image: any = {
      hidden: false,
      setPointerCapture: () => undefined,
      getBoundingClientRect: () => ({
        left: 0,
        top: 0,
        right: 100,
        bottom: 100,
        width: 100,
        height: 100,
      }),
    }
    controller.root = {
      querySelector: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }
    controller.machine = "node"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.frameObservationId = "obs-drag"
    controller.frameInputEnabled = true
    const target = {
      closest: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }

    controller.onPointerDown({
      target,
      button: 0,
      pointerId: 1,
      clientX: 10,
      clientY: 10,
    })
    controller.frameObservationId = "obs-new"
    controller.frameInputEnabled = true
    controller.onPointerUp({
      target,
      pointerId: 1,
      clientX: 30,
      clientY: 30,
      preventDefault: () => undefined,
    })
    await controller.actionQueue

    expect(sends).toHaveLength(0)
  })

  test("clears canceled pointer gestures and releases deferred observations", async () => {
    const sends: unknown[] = []
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (url: string, _method: string, body?: unknown) => {
          sends.push({ url, body })
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
    const image: any = {
      hidden: false,
      setPointerCapture: () => undefined,
      getBoundingClientRect: () => ({
        left: 0,
        top: 0,
        width: 100,
        height: 100,
      }),
    }
    controller.root = {
      querySelector: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.frameObservationId = "obs-active"
    controller.frameInputEnabled = true
    const target = {
      closest: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }

    controller.onPointerDown({
      target,
      button: 0,
      pointerId: 7,
      clientX: 10,
      clientY: 10,
    })
    controller.queueObservationDiscard("node", "window:1", "obs-old")
    await Promise.resolve()
    expect(sends).toEqual([])

    controller.onPointerCancel({ pointerId: 7 })
    await Promise.resolve()

    expect(controller.pointerStart).toBeNull()
    expect(sends).toEqual([{
      url: "/gui/frame/discard",
      body: {
        machine: "node",
        window_id: "window:1",
        observation_id: "obs-old",
      },
    }])
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

  test("expires a focus-sensitive frame before its observation token becomes stale", () => {
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
    controller.root = { querySelector: () => null }
    controller.captureRequiresFocus = true
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.frameObservationId = "obs-1"
    controller.frameInputEnabled = true
    controller.frameExpiresAt = 10_000

    expect(controller.expireFocusSensitiveFrame(9_999)).toBe(false)
    expect(controller.frameObservationId).toBe("obs-1")
    expect(controller.expireFocusSensitiveFrame(10_000)).toBe(true)
    expect(controller.frameBounds).toBeNull()
    expect(controller.frameObservationId).toBe("")
    expect(controller.frameExpiresAt).toBe(0)
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
    controller.frameObservationId = "obs-1"
    controller.frameInputEnabled = true
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
    controller.frameObservationId = "obs-1"
    controller.frameInputEnabled = true
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
    controller.frameObservationId = "obs-1"
    controller.frameInputEnabled = true
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
    controller.frameObservationId = "obs-1"
    controller.frameInputEnabled = true
    controller.refreshFrame = async () => undefined
    controller.refreshWindows = async (force: boolean) => { refreshes.push(force) }

    controller.queueAction({ type: "click", x: 1, y: 1 })
    await Promise.resolve()
    controller.queueAction({ type: "click", x: 2, y: 2 })
    releaseFirst()
    await controller.actionQueue

    expect(sends).toHaveLength(1)
    expect(refreshes).toEqual([true])
    expect(controller.frameBounds).toBeNull()
    expect(controller.frameObservationId).toBe("")
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
    controller.frameObservationId = "obs-1"
    controller.frameInputEnabled = true
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
      observation_id: "obs-1",
      bounds: { x: 0, y: 0, width: 100, height: 100 },
      actions: [{ type: "click", x: 1, y: 1 }],
    })
  })
})

describe("Native WebUI desktop frame replacement", () => {
  test("publishes new geometry only after the replacement image decodes", async () => {
    const sends: Array<{ url: string; method: string; body: unknown }> = []
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (url: string, method: "POST" | "PUT", body: Record<string, unknown>) => {
          sends.push({ url, method, body })
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
    const visibleImage: any = { src: "blob:old", hidden: false }
    controller.root = {
      querySelector: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? visibleImage : null
      ),
    }
    controller.machine = "local"
    controller.selectedWindowId = "window:1"
    controller.frameBounds = { x: 0, y: 0, width: 100, height: 100 }
    controller.frameObservationId = "obs-old"
    controller.frameMachine = "local"
    controller.frameWindowId = "window:1"
    controller.frameInputEnabled = true
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
        "X-LSM-GUI-Observation-ID": "obs-new",
        "X-LSM-GUI-Observation-TTL-S": "30",
        "X-LSM-GUI-Coordinate-Input": "1",
      },
    })) as unknown as typeof fetch
    URL.createObjectURL = () => "blob:new"
    URL.revokeObjectURL = () => undefined

    try {
      const task = controller.loadFrame("local\0window:1", new AbortController())
      await Promise.resolve()
      await Promise.resolve()
      expect(controller.frameBounds).toEqual({ x: 0, y: 0, width: 100, height: 100 })
      expect(controller.frameObservationId).toBe("obs-old")
      expect(visibleImage.src).toBe("blob:old")

      releaseDecode()
      await task
      expect(controller.frameBounds).toEqual({ x: 0, y: 0, width: 200, height: 150 })
      expect(controller.frameObservationId).toBe("obs-new")
      expect(visibleImage.src).toBe("blob:new")
      expect(sends).toEqual([{
        url: "/gui/frame/discard",
        method: "POST",
        body: {
          machine: "local",
          window_id: "window:1",
          observation_id: "obs-old",
        },
      }])
    } finally {
      globalThis.fetch = originalFetch
      URL.createObjectURL = originalCreateObjectURL
      URL.revokeObjectURL = originalRevokeObjectURL
    }
  })

  test("counts transfer and decode time against the observation lease", async () => {
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
    const image: any = { hidden: true, removeAttribute: () => undefined }
    controller.root = {
      querySelector: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }
    controller.machine = "local"
    controller.selectedWindowId = "window:1"
    controller.frameRequestKey = "local\0window:1"
    controller.frameEpoch = 0

    const originalFetch = globalThis.fetch
    const originalCreateObjectURL = URL.createObjectURL
    const originalRevokeObjectURL = URL.revokeObjectURL
    const originalNow = Date.now
    let now = 1_000
    Date.now = () => now
    globalThis.fetch = (async () => new Response(new Blob(["frame"]), {
      status: 200,
      headers: {
        "X-LSM-GUI-Window-X": "0",
        "X-LSM-GUI-Window-Y": "0",
        "X-LSM-GUI-Window-Width": "100",
        "X-LSM-GUI-Window-Height": "100",
        "X-LSM-GUI-Observation-ID": "obs-short",
        "X-LSM-GUI-Observation-TTL-S": "2",
        "X-LSM-GUI-Coordinate-Input": "1",
      },
    })) as unknown as typeof fetch
    URL.createObjectURL = () => "blob:short"
    URL.revokeObjectURL = () => undefined
    controller.decodeFrame = async () => { now = 3_100 }

    try {
      await controller.loadFrame("local\0window:1", new AbortController())
      expect(controller.frameBounds).toBeNull()
      expect(controller.frameObservationId).toBe("")
      expect(controller.frameInputEnabled).toBe(false)
    } finally {
      Date.now = originalNow
      globalThis.fetch = originalFetch
      URL.createObjectURL = originalCreateObjectURL
      URL.revokeObjectURL = originalRevokeObjectURL
    }
  })

  test("keeps view-only frames visible but disables input", async () => {
    const sends: unknown[] = []
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (_url: string, _method: string, body?: unknown) => {
          sends.push(body)
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
    const image: any = { hidden: true, src: "", removeAttribute: () => undefined }
    controller.root = {
      querySelector: (selector: string) => (
        selector === "[data-role=desktop-frame]" ? image : null
      ),
    }
    controller.machine = "local"
    controller.selectedWindowId = "window:1"
    controller.frameRequestKey = "local\0window:1"
    controller.frameEpoch = 0
    controller.decodeFrame = async () => undefined

    const originalFetch = globalThis.fetch
    const originalCreateObjectURL = URL.createObjectURL
    const originalRevokeObjectURL = URL.revokeObjectURL
    globalThis.fetch = (async () => new Response(new Blob(["frame"]), {
      status: 200,
      headers: {
        "X-LSM-GUI-Window-X": "0",
        "X-LSM-GUI-Window-Y": "0",
        "X-LSM-GUI-Window-Width": "100",
        "X-LSM-GUI-Window-Height": "100",
        "X-LSM-GUI-Observation-ID": "obs-view",
        "X-LSM-GUI-Observation-TTL-S": "30",
        "X-LSM-GUI-Coordinate-Input": "0",
      },
    })) as unknown as typeof fetch
    URL.createObjectURL = () => "blob:view"
    URL.revokeObjectURL = () => undefined

    try {
      await controller.loadFrame("local\0window:1", new AbortController())
      expect(controller.frameBounds).toEqual({ x: 0, y: 0, width: 100, height: 100 })
      expect(controller.frameInputEnabled).toBe(false)
      controller.queueAction({ type: "click", x: 1, y: 1 })
      await controller.actionQueue
      expect(sends).toHaveLength(0)
    } finally {
      globalThis.fetch = originalFetch
      URL.createObjectURL = originalCreateObjectURL
      URL.revokeObjectURL = originalRevokeObjectURL
    }
  })
  test("discards the displayed observation when the controller is destroyed", async () => {
    const sends: unknown[] = []
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (url: string, _method: string, body?: unknown) => {
          sends.push({ url, body })
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
    controller.frameObservationId = "obs-current"
    controller.frameMachine = "node"
    controller.frameWindowId = "window:9"
    controller.frameBounds = { x: 0, y: 0, width: 10, height: 10 }

    controller.destroy()
    await Promise.resolve()

    expect(sends).toEqual([{
      url: "/gui/frame/discard",
      body: {
        machine: "node",
        window_id: "window:9",
        observation_id: "obs-current",
      },
    }])
  })

  test("defers observation disposal while input is still using old tokens", async () => {
    const sends: unknown[] = []
    const context: NativePageContext = {
      api: {
        get: async () => undefined as never,
        send: async (url: string, _method: string, body?: unknown) => {
          sends.push({ url, body })
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
    controller.pendingActions = 1
    controller.queueObservationDiscard("node", "window:1", "obs-old")
    await Promise.resolve()
    expect(sends).toEqual([])

    controller.pendingActions = 0
    controller.flushObservationDiscards()
    await Promise.resolve()
    expect(sends).toEqual([{
      url: "/gui/frame/discard",
      body: {
        machine: "node",
        window_id: "window:1",
        observation_id: "obs-old",
      },
    }])
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
