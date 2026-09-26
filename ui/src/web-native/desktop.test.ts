import { describe, expect, test } from "bun:test"
import { DesktopController, SINGLE_CLICK_DELAY_MS, framePoint, wheelScrollAmount } from "./desktop"
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

describe("Native WebUI desktop queued input", () => {
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
      { ctrl = false, shift = false }: { ctrl?: boolean; shift?: boolean },
    ) => ({
      key,
      ctrlKey: ctrl,
      metaKey: false,
      altKey: false,
      shiftKey: shift,
      target,
      preventDefault: () => undefined,
    })

    controller.onKeyDown(makeEvent("+", { ctrl: true, shift: true }))
    controller.onKeyDown(makeEvent(" ", { ctrl: true }))

    expect(queued).toEqual([
      { type: "key", keys: ["CTRL", "SHIFT", "="] },
      { type: "key", keys: ["CTRL", "SPACE"] },
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
