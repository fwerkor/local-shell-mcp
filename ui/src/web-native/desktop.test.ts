import { afterEach, describe, expect, test } from "bun:test"
import { DesktopController, MAX_PENDING_DESKTOP_ACTIONS, SINGLE_CLICK_DELAY_MS, framePoint, wheelScrollAmount } from "./desktop"
import type { NativePageContext } from "./common"

const context = (): NativePageContext => ({
  api: { get: async () => undefined as never, send: async () => undefined as never },
  uiPath: "/ui", accessToken: () => null, machines: () => [], notify: () => undefined, refreshChrome: async () => undefined,
})
const original = { WebSocket: globalThis.WebSocket, location: globalThis.location, window: globalThis.window, revoke: URL.revokeObjectURL }
afterEach(() => {
  ;(globalThis as any).WebSocket = original.WebSocket
  ;(globalThis as any).location = original.location
  ;(globalThis as any).window = original.window
  URL.revokeObjectURL = original.revoke
})
function harness() {
  ;(globalThis as any).window = globalThis
  ;(globalThis as any).WebSocket = { OPEN: 1 }
  const sent: any[] = []
  const socket = { readyState: 1, send: (raw: string) => sent.push(JSON.parse(raw)), close: () => undefined }
  const c: any = new DesktopController(context())
  const image = { hidden: false, removeAttribute: (_name: string) => undefined, getBoundingClientRect: () => ({ left: 0, top: 0, right: 100, bottom: 50, width: 100, height: 50 }) }
  c.root = { querySelector: (selector: string) => selector === "[data-role=desktop-frame]" ? image : selector === "[data-role=desktop-stage]" ? { focus: () => undefined } : null }
  c.socket = socket
  c.frameUrl = "blob:frame"
  c.frameBounds = { x: 20, y: 30, width: 200, height: 100 }
  c.frameObservationId = "obs-active"
  c.frameExpiresAt = Date.now() + 10_000
  c.frameInputEnabled = true
  c.selectedWindowId = "window:1"
  return { c, socket, image, sent }
}

describe("Desktop coordinate gestures", () => {
  test("maps pixels in window-relative coordinates", () => {
    const rect = { left: 100, top: 50, right: 900, bottom: 500, width: 800, height: 450 }
    const bounds = { x: 1400, y: 200, width: 1600, height: 900 }
    expect(framePoint(100, 50, rect, bounds)).toEqual({ x: 0, y: 0 })
    expect(framePoint(500, 275, rect, bounds)).toEqual({ x: 800, y: 450 })
    expect(framePoint(899.9, 499.9, rect, bounds)).toEqual({ x: 1599, y: 899 })
  })
  test("rejects positions outside the frame", () => {
    const rect = { left: 0, top: 0, right: 100, bottom: 50, width: 100, height: 50 }
    const bounds = { x: 0, y: 0, width: 200, height: 100 }
    expect(framePoint(-1, 10, rect, bounds)).toBeNull()
    expect(framePoint(100, 10, rect, bounds)).toBeNull()
    expect(framePoint(50, 50, rect, bounds)).toBeNull()
    expect(framePoint(20, 20, rect, { ...bounds, width: 0 })).toBeNull()
  })
  test("wheel quantization and click delay", () => {
    expect(wheelScrollAmount(0)).toBe(0)
    expect(wheelScrollAmount(60)).toBe(-1)
    expect(wheelScrollAmount(-120)).toBe(2)
    expect(wheelScrollAmount(5000)).toBe(-12)
    expect(SINGLE_CLICK_DELAY_MS).toBeGreaterThanOrEqual(500)
  })
  test("double-click is sent once and triple-click suppressed", async () => {
    const { c, image, sent } = harness()
    const target = { closest: (selector: string) => selector === "[data-action]" ? null : image }
    c.onClick({ target, button: 0, detail: 2, clientX: 50, clientY: 25 })
    c.onClick({ target, button: 0, detail: 3, clientX: 50, clientY: 25 })
    await c.actionQueue
    expect(sent).toHaveLength(1)
    expect(sent[0].action).toEqual({ type: "double_click", x: 100, y: 50 })
  })
  test("drag preserves its initial frame", async () => {
    const { c, image, sent } = harness()
    const target = { closest: () => image }
    c.onPointerDown({ target, button: 0, pointerId: 3, clientX: 5, clientY: 5 })
    c.onPointerUp({ pointerId: 3, clientX: 80, clientY: 45, preventDefault: () => undefined })
    await c.actionQueue
    expect(sent[0].action).toEqual({ type: "drag", x: 10, y: 10, to_x: 160, to_y: 90 })
    expect(sent[0].observation_id).toBe("obs-active")
  })
  test("drops gestures whose observation changed", async () => {
    const { c, image, sent } = harness()
    c.onPointerDown({ target: { closest: () => image }, button: 0, pointerId: 7, clientX: 5, clientY: 5 })
    c.frameObservationId = "obs-next"
    c.onPointerUp({ pointerId: 7, clientX: 80, clientY: 40 })
    await c.actionQueue
    expect(sent).toHaveLength(0)
  })
})

describe("Desktop WebSocket transport", () => {
  test("sends structured input over socket, never HTTP tool calls", async () => {
    const { c, sent } = harness()
    c.queueAction({ type: "click", x: 10, y: 20 })
    c.queueAction({ type: "type", text: "中文" })
    await c.actionQueue
    expect(sent).toEqual([
      { type: "action", request_id: 1, observation_id: "obs-active", bounds: { x: 20, y: 30, width: 200, height: 100 }, action: { type: "click", x: 10, y: 20 } },
      { type: "action", request_id: 2, observation_id: "obs-active", bounds: { x: 20, y: 30, width: 200, height: 100 }, action: { type: "type", text: "中文" } },
    ])
    expect(c.pendingActions).toBe(2)
    c.handleControl(JSON.stringify({ type: "action-ack", request_id: 1, ok: true }))
    expect(c.pendingActions).toBe(1)
    c.handleControl(JSON.stringify({ type: "action-ack", request_id: 2, ok: true }))
    expect(c.pendingActions).toBe(0)
  })
  test("bounds pending input backlog", async () => {
    const { c, sent } = harness()
    for (let i = 0; i < MAX_PENDING_DESKTOP_ACTIONS + 3; i++) c.queueAction({ type: "click", x: i, y: 0 })
    await c.actionQueue
    expect(sent).toHaveLength(MAX_PENDING_DESKTOP_ACTIONS)
  })
  test("refuses expired frames and view-only frames", async () => {
    const { c, sent } = harness()
    c.frameExpiresAt = Date.now() - 1
    c.queueAction({ type: "click", x: 0, y: 0 })
    c.frameExpiresAt = Date.now() + 10000
    c.frameInputEnabled = false
    c.queueAction({ type: "key", keys: ["ENTER"] })
    await c.actionQueue
    expect(sent).toEqual([{ type: "refresh" }])
    expect(c.awaitingFreshFrame).toBe(true)
  })
  test("drops queued input after switching windows", async () => {
    const { c, sent } = harness()
    c.queueAction({ type: "key", keys: ["ENTER"] })
    c.invalidateActionTarget()
    await c.actionQueue
    expect(sent).toHaveLength(0)
  })
  test("updates metadata on unchanged frames without a new image", async () => {
    const { c } = harness()
    c.handleControl(JSON.stringify({ type: "frame", observation_id: "obs-new", ttl_s: 20, coordinate_input: true, bounds: { x: 50, y: 60, width: 300, height: 150 }, image: false }))
    await c.imageQueue
    expect(c.frameObservationId).toBe("obs-new")
    expect(c.frameBounds).toEqual({ x: 50, y: 60, width: 300, height: 150 })
  })
  test("unchanged frame metadata waits until the previous keyframe finishes decoding", async () => {
    const { c } = harness()
    let decode!: () => void
    const decoding = new Promise<void>((resolve) => { decode = resolve })
    c.imageQueue = decoding.then(() => c.publishFrame({
      x: 20, y: 30, width: 200, height: 100, observation_id: "keyframe",
      ttl_s: 20, coordinate_input: true,
    }))
    c.handleControl(JSON.stringify({
      type: "frame", observation_id: "newest", ttl_s: 20, coordinate_input: true,
      bounds: { x: 50, y: 60, width: 300, height: 150 }, image: false,
    }))
    expect(c.frameObservationId).toBe("obs-active")
    decode()
    await c.imageQueue
    expect(c.frameObservationId).toBe("newest")
    expect(c.frameBounds).toEqual({ x: 50, y: 60, width: 300, height: 150 })
  })
  test("does not publish metadata for a keyframe that failed decoding", async () => {
    const { c } = harness()
    c.imageQueue = Promise.reject(new Error("image decoding failed"))
    c.handleControl(JSON.stringify({
      type: "frame", observation_id: "newest", ttl_s: 20, coordinate_input: true,
      bounds: { x: 50, y: 60, width: 300, height: 150 }, image: false,
    }))
    await c.imageQueue
    expect(c.frameObservationId).toBe("obs-active")
  })
  test("failed JPEG decode disables input and ignores every unchanged frame until a successful keyframe", async () => {
    const { c, sent } = harness()
    c.displayImage = async () => { throw new Error("decode failed") }
    const frame = { x: 20, y: 30, width: 200, height: 100,
      observation_id: "bad-keyframe", ttl_s: 20, coordinate_input: true }
    await c.decodeImage(c.socket, frame, new ArrayBuffer(0))
    expect(c.waitingForKeyframe).toBe(true)
    expect(c.frameInputEnabled).toBe(false)
    expect(sent).toEqual([{ type: "refresh" }])
    for (let i = 0; i < 2; i++) {
      c.handleControl(JSON.stringify({
        type: "frame", observation_id: `after-bad-${i}`, ttl_s: 20,
        coordinate_input: true, bounds: { x: 20, y: 30, width: 200, height: 100 }, image: false,
      }))
      await c.imageQueue
    }
    expect(c.frameObservationId).toBe("obs-active")
    c.displayImage = async (_socket: unknown, metadata: unknown) => c.publishFrame(metadata)
    await c.decodeImage(c.socket, { ...frame, observation_id: "fresh-keyframe" }, new ArrayBuffer(0))
    expect(c.waitingForKeyframe).toBe(false)
    expect(c.frameObservationId).toBe("fresh-keyframe")
    expect(c.frameInputEnabled).toBe(true)
  })
  test("failed action acknowledgement disables stale input and triggers one frame refresh", async () => {
    const { c, sent } = harness()
    c.queueAction({ type: "click", x: 1, y: 2 })
    await c.actionQueue
    c.handleControl(JSON.stringify({
      type: "action-ack", request_id: 1, ok: false, refresh: true, message: "observation stale",
    }))
    expect(c.pendingActions).toBe(0)
    expect(c.frameInputEnabled).toBe(false)
    expect(c.awaitingFreshFrame).toBe(true)
    expect(c.waitingForKeyframe).toBe(true)
    expect(sent.at(-1)).toEqual({ type: "refresh" })
    c.handleControl(JSON.stringify({
      type: "frame", observation_id: "old-stale-obs", ttl_s: 20,
      coordinate_input: true, bounds: { x: 20, y: 30, width: 200, height: 100 }, image: false,
    }))
    await c.imageQueue
    expect(c.frameInputEnabled).toBe(false)
    expect(c.frameObservationId).toBe("obs-active")
    c.handleControl(JSON.stringify({
      type: "action-ack", request_id: 1, ok: false, refresh: true, message: "observation stale",
    }))
    expect(sent.filter((item: { type: string }) => item.type === "refresh")).toHaveLength(1)
    c.queueAction({ type: "click", x: 1, y: 2 })
    await c.actionQueue
    expect(sent.filter((item: { type: string }) => item.type === "action")).toHaveLength(1)
  })
  test("input expiry is anchored to metadata arrival, not a later delayed decode", async () => {
    const { c } = harness()
    const now = Date.now
    try {
      let current = 5_000
      Date.now = () => current
      c.handleControl(JSON.stringify({
        type: "frame", observation_id: "new-obs", ttl_s: 5,
        coordinate_input: true, bounds: { x: 20, y: 30, width: 200, height: 100 }, image: false,
      }))
      current += 2_000
      await c.imageQueue
      expect(c.frameExpiresAt).toBe(9_000)
      expect(c.frameObservationId).toBe("new-obs")
    } finally {
      Date.now = now
    }
  })
  test("new image metadata is not published before decode", () => {
    const { c } = harness()
    c.handleControl(JSON.stringify({ type: "frame", observation_id: "obs-next", ttl_s: 15, coordinate_input: true, bounds: { x: 0, y: 0, width: 80, height: 40 }, image: true }))
    expect(c.frameObservationId).toBe("obs-active")
    expect(c.pendingFrame.observation_id).toBe("obs-next")
  })
  test("refresh requests a stream keyframe", () => {
    const { c, sent } = harness()
    c.refreshFrame()
    expect(sent).toEqual([{ type: "refresh" }])
  })
  test("only remote acknowledgements free backlog capacity", async () => {
    const { c, sent } = harness()
    for (let i = 0; i < MAX_PENDING_DESKTOP_ACTIONS; i++) c.queueAction({ type: "click", x: i, y: 0 })
    await c.actionQueue
    expect(c.pendingActions).toBe(MAX_PENDING_DESKTOP_ACTIONS)
    c.queueAction({ type: "click", x: 10, y: 0 })
    await c.actionQueue
    expect(sent).toHaveLength(MAX_PENDING_DESKTOP_ACTIONS)
    c.handleControl(JSON.stringify({ type: "action-ack", request_id: 2, ok: true }))
    c.queueAction({ type: "click", x: 11, y: 0 })
    await c.actionQueue
    expect(sent).toHaveLength(MAX_PENDING_DESKTOP_ACTIONS + 1)
    c.handleControl(JSON.stringify({ type: "action-ack", request_id: 5, ok: false, message: "stale" }))
    expect(c.pendingActions).toBe(MAX_PENDING_DESKTOP_ACTIONS - 1)
  })
  test("refreshes expired frames once and accepts input on fresh frames", async () => {
    const { c, sent } = harness()
    c.frameExpiresAt = 0
    c.queueAction({ type: "click", x: 1, y: 1 })
    c.queueAction({ type: "click", x: 2, y: 2 })
    await c.actionQueue
    expect(sent).toEqual([{ type: "refresh" }])
    c.publishFrame({ x: 20, y: 30, width: 200, height: 100, observation_id: "obs-new", ttl_s: 20, coordinate_input: true })
    c.queueAction({ type: "click", x: 3, y: 3 })
    await c.actionQueue
    expect(sent.at(-1)?.observation_id).toBe("obs-new")
  })
  test("disconnect closes the stream and clears frame state", () => {
    const { c, socket } = harness()
    let closed = false
    socket.close = () => { closed = true }
    URL.revokeObjectURL = () => undefined
    c.disconnect()
    expect(closed).toBe(true)
    expect(c.socket).toBeNull()
    expect(c.frameObservationId).toBe("")
    expect(c.frameInputEnabled).toBe(false)
  })
  test("reconnecting decodes the new stream without waiting for the prior socket image", async () => {
    const { c } = harness()
    let finishOldDecode!: () => void
    c.imageQueue = new Promise<void>((resolve) => { finishOldDecode = resolve })
    ;(globalThis as any).location = { protocol: "https:", host: "example.test" }
    ;(globalThis as any).WebSocket = class {
      static OPEN = 1
      binaryType = ""
      readyState = 1
      constructor(_url: URL) {}
      close() {}
    }
    URL.revokeObjectURL = () => undefined
    c.displayImage = async (_socket: WebSocket, metadata: unknown) => c.publishFrame(metadata)
    c.connect()
    const newSocket = c.socket
    newSocket.onmessage({ data: JSON.stringify({
      type: "frame", observation_id: "new-stream-obs", ttl_s: 20,
      coordinate_input: true, bounds: { x: 0, y: 0, width: 80, height: 40 }, image: true,
    }) })
    newSocket.onmessage({ data: new ArrayBuffer(3) })
    await c.imageQueue
    expect(c.frameObservationId).toBe("new-stream-obs")
    finishOldDecode()
  })
  test("connect uses authenticated websocket endpoint, not HTTP polling", () => {
    const { c } = harness()
    let uri = ""
    ;(globalThis as any).location = { protocol: "https:", host: "example.test" }
    ;(globalThis as any).WebSocket = class {
      static OPEN = 1
      binaryType = ""
      constructor(url: URL) { uri = String(url) }
      close() {}
    }
    URL.revokeObjectURL = () => undefined
    c.connect()
    expect(uri).toContain("wss://example.test/ui/ws/desktop?")
    expect(uri).toContain("machine=local")
    expect(uri).toContain("window_id=window%3A1")
  })
})
