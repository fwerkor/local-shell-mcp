import { describe, expect, test } from "bun:test"
import { TerminalsController } from "./terminals"

describe("Native WebUI terminal scrolling", () => {
  test("leaves wheel input to mouse-aware terminal applications", () => {
    let prevented = false
    let stopped = false
    let synced = false
    const controller = {
      scrollbackSupported: true,
      terminal: { modes: { mouseTrackingMode: "vt200" } },
      queueScrollbackSync: () => { synced = true },
    }
    const event = {
      deltaY: -120,
      preventDefault: () => { prevented = true },
      stopPropagation: () => { stopped = true },
    }

    ;(TerminalsController.prototype as any).onTerminalWheel.call(controller, event)

    expect(prevented).toBe(false)
    expect(stopped).toBe(false)
    expect(synced).toBe(true)
  })

  test("uses tmux scrollback for ordinary shell wheel input", () => {
    let prevented = false
    let stopped = false
    const scrollbar = { scrollTop: 40 }
    const controller = {
      scrollbackSupported: true,
      terminal: { modes: { mouseTrackingMode: "none" } },
      root: { querySelector: () => scrollbar },
    }
    const event = {
      deltaY: -120,
      preventDefault: () => { prevented = true },
      stopPropagation: () => { stopped = true },
    }

    ;(TerminalsController.prototype as any).onTerminalWheel.call(controller, event)

    expect(prevented).toBe(true)
    expect(stopped).toBe(true)
    expect(scrollbar.scrollTop).toBe(35)
  })

  test("operates tmux scrollback from the keyboard", () => {
    let prevented = false
    let stopped = false
    let requested = -1
    const controller = {
      scrollbackSupported: true,
      scrollbackHistory: 100,
      scrollbackPosition: 10,
      terminal: { rows: 20 },
      renderScrollbar: () => {},
      queueScrollRequest: (position: number) => { requested = position },
    }
    const event = {
      key: "PageUp",
      preventDefault: () => { prevented = true },
      stopPropagation: () => { stopped = true },
    }

    ;(TerminalsController.prototype as any).onScrollbarKeyDown.call(controller, event)

    expect(prevented).toBe(true)
    expect(stopped).toBe(true)
    expect(controller.scrollbackPosition).toBe(30)
    expect(requested).toBe(30)
  })

  test("keeps at most one scroll request in flight", async () => {
    const previousWindow = (globalThis as any).window
    ;(globalThis as any).window = { setTimeout, clearTimeout }
    const sent: string[] = []
    const socket = {
      readyState: WebSocket.OPEN,
      send: (value: string) => { sent.push(value) },
    }
    const controller: any = {
      scrollbackSupported: true,
      scrollbackHistory: 100,
      scrollbackPosition: 0,
      pendingScrollPosition: null,
      scrollRequestTimer: null,
      scrollRequestInFlight: null,
      scrollRequestSequence: 0,
      socket,
      renderScrollbar: () => {},
    }
    controller.scheduleScrollRequest = (delay: number) =>
      (TerminalsController.prototype as any).scheduleScrollRequest.call(controller, delay)

    try {
      ;(TerminalsController.prototype as any).queueScrollRequest.call(controller, 10)
      await Bun.sleep(50)
      expect(sent.length).toBe(1)
      expect(JSON.parse(sent[0])).toEqual({ type: "scrollback", position: 10, request_id: 1 })

      ;(TerminalsController.prototype as any).queueScrollRequest.call(controller, 20)
      ;(TerminalsController.prototype as any).queueScrollRequest.call(controller, 30)
      await Bun.sleep(50)
      expect(sent.length).toBe(1)

      ;(TerminalsController.prototype as any).handleSocketControl.call(
        controller,
        JSON.stringify({ type: "scrollback", supported: true, history: 100, position: 10, request_id: 1 }),
      )
      await Bun.sleep(10)

      expect(sent.length).toBe(2)
      expect(JSON.parse(sent[1])).toEqual({ type: "scrollback", position: 30, request_id: 2 })
    } finally {
      ;(globalThis as any).window = previousWindow
    }
  })

  test("releases an in-flight request after a failure acknowledgement", () => {
    let scheduled = -1
    const controller: any = {
      scrollRequestInFlight: 7,
      pendingScrollPosition: 42,
      scheduleScrollRequest: (delay: number) => { scheduled = delay },
    }

    const handled = (TerminalsController.prototype as any).handleSocketControl.call(
      controller,
      JSON.stringify({ type: "scrollback-ack", request_id: 7 }),
    )

    expect(handled).toBe(true)
    expect(controller.scrollRequestInFlight).toBe(null)
    expect(scheduled).toBe(0)
  })
})

describe("Native WebUI terminal session filtering", () => {
  test("switches only among sessions visible under the active filter", () => {
    let selected = ""
    const controller: any = {
      sessions: [
        { session_id: "build-a" },
        { session_id: "hidden" },
        { session_id: "build-b" },
      ],
      sessionQuery: "BUILD",
      selectedSessionId: "build-a",
      selectSession: (sessionId: string) => { selected = sessionId },
    }
    controller.visibleSessions = () => (TerminalsController.prototype as any).visibleSessions.call(controller)

    ;(TerminalsController.prototype as any).switchSession.call(controller, 1)

    expect(selected).toBe("build-b")
  })

  test("uses the first visible session when the active session is filtered out", () => {
    let selected = ""
    const controller: any = {
      sessions: [
        { session_id: "hidden" },
        { session_id: "build-a" },
        { session_id: "build-b" },
      ],
      sessionQuery: "build",
      selectedSessionId: "hidden",
      selectSession: (sessionId: string) => { selected = sessionId },
    }
    controller.visibleSessions = () => (TerminalsController.prototype as any).visibleSessions.call(controller)

    ;(TerminalsController.prototype as any).switchSession.call(controller, -1)

    expect(selected).toBe("build-a")
  })
})
