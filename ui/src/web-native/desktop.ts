import type { Machine } from "../types"
import {
  BaseController,
  button,
  escapeHtml,
  queryString,
  type NativePageContext,
} from "./common"

type GuiBounds = {
  x: number
  y: number
  width: number
  height: number
}

type GuiWindow = {
  id: string
  title?: string
  app?: string
  pid?: number
  bounds?: GuiBounds
}

type GuiWindowsPayload = {
  machine: string
  backend?: string
  platform?: string
  windows: GuiWindow[]
  capabilities?: Record<string, unknown>
}

type GuiAction = {
  type: "click" | "double_click" | "right_click" | "scroll" | "drag" | "type" | "key"
  x?: number
  y?: number
  to_x?: number
  to_y?: number
  delta_y?: number
  text?: string
  keys?: string | string[]
}

type Point = { x: number; y: number }

type PointerStart = {
  point: Point
  bounds: GuiBounds
  observationId: string
  clientX: number
  clientY: number
  pointerId: number
}

export const SINGLE_CLICK_DELAY_MS = 500
export const MAX_PENDING_DESKTOP_ACTIONS = 4

const PHYSICAL_KEY_CODES: Record<string, string> = {
  Digit0: "0",
  Digit1: "1",
  Digit2: "2",
  Digit3: "3",
  Digit4: "4",
  Digit5: "5",
  Digit6: "6",
  Digit7: "7",
  Digit8: "8",
  Digit9: "9",
  Minus: "-",
  Equal: "=",
  BracketLeft: "[",
  BracketRight: "]",
  Backslash: "\\",
  Semicolon: ";",
  Quote: "'",
  Comma: ",",
  Period: ".",
  Slash: "/",
  Backquote: "`",
}

const SPECIAL_KEYS: Record<string, string> = {
  Enter: "ENTER",
  Tab: "TAB",
  Backspace: "BACKSPACE",
  Delete: "DELETE",
  Escape: "ESC",
  ArrowLeft: "LEFT",
  ArrowRight: "RIGHT",
  ArrowUp: "UP",
  ArrowDown: "DOWN",
  Home: "HOME",
  End: "END",
  PageUp: "PAGEUP",
  PageDown: "PAGEDOWN",
  " ": "SPACE",
}

function numericHeader(response: Response, name: string): number {
  const value = Number(response.headers.get(name) || 0)
  return Number.isFinite(value) ? value : 0
}

function guiCapableMachines(machines: Machine[]): Machine[] {
  const capable = machines.filter((machine) => (
    machine.name === "local"
    || (machine.capabilities || []).some((capability) => capability.toLowerCase() === "gui")
  ))
  return capable.length ? capable : machines
}

export function framePoint(
  clientX: number,
  clientY: number,
  rect: Pick<DOMRect, "left" | "top" | "right" | "bottom" | "width" | "height">,
  bounds: GuiBounds,
): Point | null {
  if (!rect.width || !rect.height || !bounds.width || !bounds.height) return null
  if (clientX < rect.left || clientX >= rect.right || clientY < rect.top || clientY >= rect.bottom) return null
  return {
    x: Math.max(0, Math.min(bounds.width - 1, Math.floor((clientX - rect.left) * bounds.width / rect.width))),
    y: Math.max(0, Math.min(bounds.height - 1, Math.floor((clientY - rect.top) * bounds.height / rect.height))),
  }
}

export function wheelScrollAmount(deltaY: number): number {
  if (!deltaY) return 0
  return -Math.sign(deltaY) * Math.max(1, Math.min(12, Math.round(Math.abs(deltaY) / 60)))
}

export class DesktopController extends BaseController {
  private machine = "local"
  private windows: GuiWindow[] = []
  private selectedWindowId = ""
  private backend = ""
  private captureRequiresFocus = false
  private loadingWindows = false
  private pendingWindowsRefresh = false
  private pendingWindowsForceFrame = false
  private socket: WebSocket | null = null
  private frameUrl = ""
  private frameBounds: GuiBounds | null = null
  private frameObservationId = ""
  private frameExpiresAt = 0
  private frameInputEnabled = false
  private actionTargetEpoch = 0
  private actionQueue: Promise<void> = Promise.resolve()
  private pendingActions = 0
  private nextRequestId = 0
  private pendingRequestIds = new Set<number>()
  private awaitingFreshFrame = false
  private pointerStart: PointerStart | null = null
  private suppressClickUntil = 0
  private clickTimer: number | null = null
  private wheelTimer: number | null = null
  private wheelDelta = 0
  private wheelPoint: Point | null = null
  private wheelBounds: GuiBounds | null = null
  private wheelObservationId = ""
  private imageQueue: Promise<void> = Promise.resolve()
  private pendingFrame: (GuiBounds & { observation_id: string; ttl_s: number; coordinate_input: boolean }) | null = null

  constructor(context: NativePageContext) {
    super(context)
  }

  private invalidateActionTarget(): void {
    this.actionTargetEpoch += 1
  }

  mount(root: HTMLElement): void {
    this.root = root
    this.root.innerHTML = `
      <section class="native-page desktop-page">
        <div class="native-toolbar desktop-toolbar">
          <div class="toolbar-group">
            <label>Machine <select data-role="desktop-machine"></select></label>
            <label>Window <select data-role="desktop-window"></select></label>
            <span class="desktop-connection" data-role="desktop-connection"><i></i><strong>Loading</strong></span>
          </div>
          <div class="toolbar-actions">
            ${button("Refresh windows", "desktop-refresh-windows")}
            ${button("Refresh frame", "desktop-refresh-frame", { primary: true })}
          </div>
        </div>
        <section class="native-panel desktop-panel">
          <header>
            <div>
              <h3 data-role="desktop-title">Desktop window</h3>
              <p data-role="desktop-meta">Choose a window to begin.</p>
            </div>
            <span data-role="desktop-scale">—</span>
          </header>
          <div class="desktop-stage-wrap">
            <div class="desktop-stage" data-role="desktop-stage" tabindex="0" aria-label="Interactive desktop window">
              <div class="desktop-placeholder" data-role="desktop-placeholder">
                <strong>Select a GUI window</strong>
                <span>Mouse, wheel, keyboard shortcuts, and text input are forwarded to the selected native window.</span>
              </div>
              <img data-role="desktop-frame" alt="Selected native application window" draggable="false" hidden/>
              <div class="desktop-input-pulse" data-role="desktop-input-pulse" hidden>Sending input…</div>
            </div>
          </div>
          <footer class="desktop-footer">
            <form class="desktop-text-dock" data-role="desktop-text-form">
              <span>Text</span>
              <input data-role="desktop-text" type="text" autocomplete="off" placeholder="Type text, including IME/CJK, then press Enter" disabled/>
              <button class="native-button" type="submit" disabled>Send</button>
            </form>
            <div class="desktop-help">
              <span>Click · double-click · right-click · drag · wheel</span>
              <span>Focus the frame for arrows, Enter, Tab, Backspace, Delete, Ctrl/⌘ shortcuts</span>
            </div>
          </footer>
        </section>
      </section>
    `

    this.listen(this.root, "change", (event) => this.onChange(event))
    this.listen(this.root, "click", (event) => this.onClick(event))
    this.listen(this.root, "pointerdown", (event) => this.onPointerDown(event as PointerEvent))
    this.listen(this.root, "pointerup", (event) => this.onPointerUp(event as PointerEvent))
    this.listen(this.root, "pointercancel", (event) => this.onPointerCancel(event as PointerEvent))
    this.listen(this.root, "contextmenu", (event) => this.onContextMenu(event as MouseEvent))
    this.listen(this.root, "wheel", (event) => this.onWheel(event as WheelEvent), { passive: false })
    this.listen(this.root, "keydown", (event) => this.onKeyDown(event as KeyboardEvent))
    const form = this.root.querySelector<HTMLFormElement>("[data-role=desktop-text-form]")
    if (form) this.listen(form, "submit", (event) => this.onTextSubmit(event as SubmitEvent))

    void this.refresh()
  }

  async refresh(): Promise<void> {
    await this.refreshWindows(true)
  }

  override destroy(): void {
    this.invalidateActionTarget()
    this.disconnect()
    super.destroy()
  }

  private machines(): Machine[] {
    return guiCapableMachines(this.context.machines())
  }

  private currentWindow(): GuiWindow | undefined {
    return this.windows.find((window) => window.id === this.selectedWindowId)
  }

  private renderSelectors(): void {
    const machines = this.machines()
    if (!machines.some((machine) => machine.name === this.machine)) {
      this.machine = machines.some((machine) => machine.name === "local")
        ? "local"
        : machines[0]?.name || "local"
      this.selectedWindowId = ""
      this.windows = []
      this.invalidateActionTarget()
      this.disconnect()
    }

    const machineSelect = this.root.querySelector<HTMLSelectElement>("[data-role=desktop-machine]")
    if (machineSelect) {
      machineSelect.innerHTML = machines.map((machine) => (
        `<option value="${escapeHtml(machine.name)}"${machine.name === this.machine ? " selected" : ""}>${escapeHtml(machine.name)}${machine.status && machine.name !== "local" ? ` · ${escapeHtml(machine.status)}` : ""}</option>`
      )).join("")
    }

    const windowSelect = this.root.querySelector<HTMLSelectElement>("[data-role=desktop-window]")
    if (windowSelect) {
      windowSelect.disabled = !this.windows.length
      windowSelect.innerHTML = this.windows.length
        ? this.windows.map((window) => {
            const title = window.title || "Untitled window"
            const app = window.app ? `${window.app} — ` : ""
            return `<option value="${escapeHtml(window.id)}"${window.id === this.selectedWindowId ? " selected" : ""}>${escapeHtml(app + title)}</option>`
          }).join("")
        : '<option value="">No GUI windows</option>'
    }
    this.renderStatus()
  }

  private renderStatus(message?: string, error = false): void {
    const current = this.currentWindow()
    const title = this.root.querySelector<HTMLElement>("[data-role=desktop-title]")
    const meta = this.root.querySelector<HTMLElement>("[data-role=desktop-meta]")
    const connection = this.root.querySelector<HTMLElement>("[data-role=desktop-connection]")
    const scale = this.root.querySelector<HTMLElement>("[data-role=desktop-scale]")
    const text = this.root.querySelector<HTMLInputElement>("[data-role=desktop-text]")
    const submit = this.root.querySelector<HTMLButtonElement>("[data-role=desktop-text-form] button")

    if (title) title.textContent = current ? current.title || current.app || "Desktop window" : "Desktop window"
    if (meta) {
      const bounds = this.frameBounds || current?.bounds
      const dimensions = bounds?.width && bounds?.height ? `${bounds.width} × ${bounds.height}` : "size unavailable"
      meta.textContent = message || (
        current
          ? [current.app, this.backend, dimensions, this.machine].filter(Boolean).join(" · ")
          : "Choose a window to begin."
      )
    }
    if (scale) scale.textContent = this.frameBounds ? "Window coordinates" : "—"
    if (connection) {
      connection.classList.toggle("error", error)
      connection.classList.toggle("online", Boolean(current && this.frameBounds && !error))
      const label = connection.querySelector<HTMLElement>("strong")
      if (label) label.textContent = error ? "Unavailable" : current ? this.frameBounds ? "Live" : "Connecting" : "Idle"
    }
    const enabled = Boolean(current && this.frameBounds && this.frameInputEnabled)
    if (text) text.disabled = !enabled
    if (submit) submit.disabled = !enabled
  }

  private async refreshWindows(forceFrame: boolean): Promise<void> {
    if (this.loadingWindows) {
      this.pendingWindowsRefresh = true
      this.pendingWindowsForceFrame ||= forceFrame
      return
    }
    this.loadingWindows = true
    const requestedMachine = this.machine
    try {
      const payload = await this.context.api.get<GuiWindowsPayload>(
        `/gui/windows${queryString({ machine: requestedMachine })}`,
      )
      if (this.destroyed || requestedMachine !== this.machine) return
      const previous = this.selectedWindowId
      this.windows = payload.windows || []
      this.backend = payload.backend || ""
      this.captureRequiresFocus = payload.capabilities?.capture_requires_focus === true
      if (!this.windows.some((window) => window.id === previous)) {
        this.selectedWindowId = this.windows[0]?.id || ""
        this.invalidateActionTarget()
        this.disconnect()
      }
      this.renderSelectors()
      if (this.selectedWindowId && (forceFrame || !this.socket)) this.connect()
    } catch (error) {
      if (requestedMachine !== this.machine) return
      this.windows = []
      this.selectedWindowId = ""
      this.invalidateActionTarget()
      this.disconnect()
      this.renderSelectors()
      this.renderStatus(error instanceof Error ? error.message : String(error), true)
    } finally {
      this.loadingWindows = false
      const targetChanged = requestedMachine !== this.machine
      if (!this.destroyed && (this.pendingWindowsRefresh || targetChanged)) {
        const nextForceFrame = this.pendingWindowsForceFrame || targetChanged
        this.pendingWindowsRefresh = false
        this.pendingWindowsForceFrame = false
        void this.refreshWindows(nextForceFrame)
      } else {
        this.pendingWindowsRefresh = false
        this.pendingWindowsForceFrame = false
      }
    }
  }

  private protocols(): string[] {
    const protocols = ["lsm-ui"]
    const token = this.context.accessToken()
    if (token) {
      let binary = ""
      for (const byte of new TextEncoder().encode(token)) binary += String.fromCharCode(byte)
      protocols.push(`bearer.${btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}`)
    }
    return protocols
  }

  private connect(): void {
    if (!this.selectedWindowId) return
    this.disconnect()
    const scheme = location.protocol === "https:" ? "wss:" : "ws:"
    const url = new URL(`${scheme}//${location.host}${this.context.uiPath}/ws/desktop`)
    url.searchParams.set("machine", this.machine)
    url.searchParams.set("window_id", this.selectedWindowId)
    const socket = new WebSocket(url, this.protocols())
    socket.binaryType = "arraybuffer"
    this.socket = socket
    this.renderStatus("Connecting to desktop…")
    socket.onmessage = (event) => {
      if (socket !== this.socket) return
      if (typeof event.data === "string") {
        this.handleControl(event.data)
      } else {
        const metadata = this.pendingFrame
        this.pendingFrame = null
        if (!metadata) return
        this.imageQueue = this.imageQueue.then(
          () => this.displayImage(socket, metadata, event.data as Blob | ArrayBuffer),
          () => this.displayImage(socket, metadata, event.data as Blob | ArrayBuffer),
        )
      }
    }
    socket.onerror = () => {
      if (socket === this.socket) this.renderStatus("Desktop stream connection failed", true)
    }
    socket.onclose = (event) => {
      if (socket !== this.socket) return
      this.disconnect()
      this.renderStatus(event.reason || "Desktop disconnected; select Refresh windows to reconnect", true)
    }
  }

  private handleControl(raw: string): void {
    let message: Record<string, unknown>
    try {
      message = JSON.parse(raw) as Record<string, unknown>
    } catch {
      return
    }
    if (message.type === "error") {
      this.context.notify(String(message.message || "Desktop error"), "error")
      return
    }
    if (message.type === "action-ack" && typeof message.request_id === "number") {
      if (this.pendingRequestIds.delete(message.request_id)) {
        this.pendingActions = this.pendingRequestIds.size
        this.renderInputPulse()
      }
      if (message.ok === false) this.context.notify(String(message.message || "Desktop input failed"), "error")
      return
    }
    if (message.type !== "frame") return
    if (typeof message.warning === "string") this.context.notify(message.warning, "error")
    const bounds = message.bounds as GuiBounds | undefined
    const observationId = message.observation_id
    const ttl = message.ttl_s
    if (!bounds || !bounds.width || !bounds.height || typeof observationId !== "string" || typeof ttl !== "number") return
    const metadata = { ...bounds, observation_id: observationId, ttl_s: ttl, coordinate_input: message.coordinate_input === true }
    if (message.image) {
      this.pendingFrame = metadata
    } else if (this.frameUrl) {
      const socket = this.socket
      const publish = () => {
        if (socket === this.socket && this.frameUrl) this.publishFrame(metadata)
      }
      this.imageQueue = this.imageQueue.then(publish, () => undefined)
    }
  }

  private publishFrame(data: GuiBounds & { observation_id: string; ttl_s: number; coordinate_input: boolean }): void {
    this.awaitingFreshFrame = false
    this.frameBounds = { x: data.x, y: data.y, width: data.width, height: data.height }
    this.frameObservationId = data.observation_id
    this.frameExpiresAt = Date.now() + Math.max(0, data.ttl_s * 1000 - 1000)
    this.frameInputEnabled = data.coordinate_input
    this.renderStatus()
  }

  private async displayImage(socket: WebSocket, metadata: GuiBounds & { observation_id: string; ttl_s: number; coordinate_input: boolean }, data: Blob | ArrayBuffer): Promise<void> {
    const blob = data instanceof Blob ? data : new Blob([data], { type: "image/jpeg" })
    const url = URL.createObjectURL(blob)
    try {
      const decoded = document.createElement("img")
      decoded.src = url
      await decoded.decode()
      if (socket !== this.socket) return
      const image = this.root.querySelector<HTMLImageElement>("[data-role=desktop-frame]")
      const placeholder = this.root.querySelector<HTMLElement>("[data-role=desktop-placeholder]")
      if (image) {
        image.src = url
        image.hidden = false
      }
      if (placeholder) placeholder.hidden = true
      const previous = this.frameUrl
      this.frameUrl = url
      this.publishFrame(metadata)
      if (previous) URL.revokeObjectURL(previous)
    } finally {
      if (this.frameUrl !== url) URL.revokeObjectURL(url)
    }
  }

  private refreshFrame(): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "refresh" }))
    } else {
      this.connect()
    }
  }

  private disconnect(): void {
    const socket = this.socket
    this.socket = null
    if (socket) {
      socket.onclose = null
      socket.close()
    }
    this.pendingFrame = null
    this.pendingRequestIds.clear()
    this.pendingActions = 0
    this.awaitingFreshFrame = false
    this.cancelPendingPointerInput()
    this.frameBounds = null
    this.frameObservationId = ""
    this.frameExpiresAt = 0
    this.frameInputEnabled = false
    if (this.frameUrl) URL.revokeObjectURL(this.frameUrl)
    this.frameUrl = ""
    const image = this.root?.querySelector<HTMLImageElement>("[data-role=desktop-frame]")
    const placeholder = this.root?.querySelector<HTMLElement>("[data-role=desktop-placeholder]")
    if (image) {
      image.hidden = true
      image.removeAttribute("src")
    }
    if (placeholder) placeholder.hidden = false
  }

  private flushObservationDiscards(): void {
    // The server stream owns observation lifetimes; the browser never discards them.
  }

  private pointForEvent(event: MouseEvent): Point | null {
    if (!this.frameInputEnabled) return null
    const image = this.root.querySelector<HTMLImageElement>("[data-role=desktop-frame]")
    const bounds = this.frameBounds
    if (!image || image.hidden || !bounds?.width || !bounds.height) return null
    return framePoint(event.clientX, event.clientY, image.getBoundingClientRect(), bounds)
  }

  private queueAction(action: GuiAction, observedBounds?: GuiBounds, observedObservationId?: string): void {
    const socket = this.socket
    const epoch = this.actionTargetEpoch
    const bounds = observedBounds || this.frameBounds
    const observation_id = observedObservationId || this.frameObservationId
    if (!socket || socket.readyState !== WebSocket.OPEN || !bounds || !observation_id || !this.frameInputEnabled) return
    if (Date.now() >= this.frameExpiresAt) {
      if (!this.awaitingFreshFrame) {
        this.awaitingFreshFrame = true
        this.refreshFrame()
        this.context.notify("Desktop frame expired. Refreshing; retry input when the updated frame appears.", "error")
      }
      return
    }
    if (this.pendingRequestIds.size >= MAX_PENDING_DESKTOP_ACTIONS) {
      this.context.notify("Desktop input is busy; wait for the previous actions to finish.", "error")
      return
    }
    const request_id = ++this.nextRequestId
    this.pendingRequestIds.add(request_id)
    this.pendingActions = this.pendingRequestIds.size
    this.renderInputPulse()
    const run = () => {
      let sent = false
      try {
        if (socket !== this.socket || epoch !== this.actionTargetEpoch) return
        socket.send(JSON.stringify({ type: "action", request_id, observation_id, bounds, action }))
        sent = true
      } catch (error) {
        this.context.notify(error instanceof Error ? error.message : String(error), "error")
      } finally {
        if (!sent) {
          this.pendingRequestIds.delete(request_id)
          this.pendingActions = this.pendingRequestIds.size
          this.renderInputPulse()
        }
      }
    }
    this.actionQueue = this.actionQueue.then(run, run)
  }

  private cancelPendingPointerInput(): void {
    if (this.clickTimer !== null) window.clearTimeout(this.clickTimer)
    if (this.wheelTimer !== null) window.clearTimeout(this.wheelTimer)
    this.clickTimer = null
    this.wheelTimer = null
    this.wheelDelta = 0
    this.wheelPoint = null
    this.wheelBounds = null
    this.wheelObservationId = ""
    this.pointerStart = null
  }

  private renderInputPulse(): void {
    const pulse = this.root.querySelector<HTMLElement>("[data-role=desktop-input-pulse]")
    if (pulse) pulse.hidden = this.pendingActions === 0
  }

  private onChange(event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLSelectElement)) return
    if (target.dataset.role === "desktop-machine") {
      if (target.value === this.machine) return
      this.machine = target.value
      this.windows = []
      this.selectedWindowId = ""
      this.backend = ""
      this.captureRequiresFocus = false
      this.invalidateActionTarget()
      this.disconnect()
      this.renderSelectors()
      void this.refreshWindows(true)
      return
    }
    if (target.dataset.role === "desktop-window") {
      if (target.value === this.selectedWindowId) return
      this.selectedWindowId = target.value
      this.invalidateActionTarget()
      this.disconnect()
      this.renderSelectors()
      this.connect()
    }
  }

  private onClick(event: MouseEvent): void {
    const actionTarget = (event.target as HTMLElement).closest<HTMLElement>("[data-action]")
    if (actionTarget?.dataset.action === "desktop-refresh-windows") {
      void this.refreshWindows(true)
      return
    }
    if (actionTarget?.dataset.action === "desktop-refresh-frame") {
      this.refreshFrame()
      return
    }

    const image = (event.target as HTMLElement).closest<HTMLImageElement>("[data-role=desktop-frame]")
    if (!image || event.button !== 0 || Date.now() < this.suppressClickUntil) return
    const point = this.pointForEvent(event)
    const observedBounds = this.frameBounds ? { ...this.frameBounds } : null
    const observedObservationId = this.frameObservationId
    if (!point || !observedBounds || !observedObservationId) return
    this.root.querySelector<HTMLElement>("[data-role=desktop-stage]")?.focus({ preventScroll: true })
    if (event.detail === 2) {
      if (this.clickTimer !== null) {
        window.clearTimeout(this.clickTimer)
        this.clickTimer = null
      }
      this.queueAction(
        { type: "double_click", ...point },
        observedBounds,
        observedObservationId,
      )
      return
    }
    if (event.detail > 2) return
    if (this.clickTimer !== null) window.clearTimeout(this.clickTimer)
    this.clickTimer = window.setTimeout(() => {
      this.clickTimer = null
      this.queueAction(
        { type: "click", ...point },
        observedBounds,
        observedObservationId,
      )
      this.flushObservationDiscards()
    }, SINGLE_CLICK_DELAY_MS)
  }

  private onPointerDown(event: PointerEvent): void {
    if (event.button !== 0) return
    const image = (event.target as HTMLElement).closest<HTMLImageElement>("[data-role=desktop-frame]")
    if (!image) return
    const point = this.pointForEvent(event)
    const bounds = this.frameBounds ? { ...this.frameBounds } : null
    const observationId = this.frameObservationId
    if (!point || !bounds || !observationId) return
    this.pointerStart = {
      point,
      bounds,
      observationId,
      clientX: event.clientX,
      clientY: event.clientY,
      pointerId: event.pointerId,
    }
    image.setPointerCapture?.(event.pointerId)
  }

  private onPointerUp(event: PointerEvent): void {
    const start = this.pointerStart
    if (!start || start.pointerId !== event.pointerId) return
    this.pointerStart = null
    if (this.frameObservationId !== start.observationId) {
      this.flushObservationDiscards()
      return
    }
    const end = this.pointForEvent(event)
    if (!end) return
    const distance = Math.hypot(event.clientX - start.clientX, event.clientY - start.clientY)
    if (distance < 6) return
    event.preventDefault()
    this.suppressClickUntil = Date.now() + 350
    this.queueAction({
      type: "drag",
      x: start.point.x,
      y: start.point.y,
      to_x: end.x,
      to_y: end.y,
    }, start.bounds, start.observationId)
  }

  private onPointerCancel(event: PointerEvent): void {
    const start = this.pointerStart
    if (!start || start.pointerId !== event.pointerId) return
    this.pointerStart = null
    this.flushObservationDiscards()
  }

  private onContextMenu(event: MouseEvent): void {
    const image = (event.target as HTMLElement).closest<HTMLImageElement>("[data-role=desktop-frame]")
    if (!image) return
    const point = this.pointForEvent(event)
    const bounds = this.frameBounds ? { ...this.frameBounds } : null
    const observationId = this.frameObservationId
    if (!point || !bounds || !observationId) return
    event.preventDefault()
    this.root.querySelector<HTMLElement>("[data-role=desktop-stage]")?.focus({ preventScroll: true })
    this.queueAction({ type: "right_click", ...point }, bounds, observationId)
  }

  private onWheel(event: WheelEvent): void {
    const image = (event.target as HTMLElement).closest<HTMLImageElement>("[data-role=desktop-frame]")
    if (!image) return
    const point = this.pointForEvent(event)
    const bounds = this.frameBounds ? { ...this.frameBounds } : null
    const observationId = this.frameObservationId
    if (!point || !bounds || !observationId) return
    event.preventDefault()
    if (
      this.wheelObservationId
      && this.wheelObservationId !== observationId
    ) {
      this.wheelDelta = 0
    }
    this.wheelDelta += event.deltaY
    this.wheelPoint = point
    this.wheelBounds = bounds
    this.wheelObservationId = observationId
    if (this.wheelTimer !== null) window.clearTimeout(this.wheelTimer)
    this.wheelTimer = window.setTimeout(() => {
      this.wheelTimer = null
      const delta = this.wheelDelta
      const target = this.wheelPoint
      const observedBounds = this.wheelBounds
      const observedObservationId = this.wheelObservationId
      this.wheelDelta = 0
      this.wheelPoint = null
      this.wheelBounds = null
      this.wheelObservationId = ""
      if (!target || !observedBounds || !observedObservationId || !delta) {
        this.flushObservationDiscards()
        return
      }
      const amount = wheelScrollAmount(delta)
      if (amount) {
        this.queueAction(
          { type: "scroll", ...target, delta_y: amount },
          observedBounds,
          observedObservationId,
        )
      }
      this.flushObservationDiscards()
    }, 55)
  }

  private onKeyDown(event: KeyboardEvent): void {
    const stage = this.root.querySelector<HTMLElement>("[data-role=desktop-stage]")
    if (!stage || !stage.contains(event.target as Node)) return
    if ((event.target as HTMLElement).closest("input,textarea,select,button")) return

    const special = SPECIAL_KEYS[event.key]
    const hasCommandModifier = event.ctrlKey || event.metaKey || event.altKey
    if (!special && event.key.length === 1 && !hasCommandModifier) {
      event.preventDefault()
      this.queueAction({ type: "type", text: event.key })
      return
    }

    const physicalKey = hasCommandModifier ? PHYSICAL_KEY_CODES[event.code] : undefined
    const key = special || physicalKey || (event.key.length === 1 ? event.key.toUpperCase() : "")
    if (!key) return
    const parts: string[] = []
    if (event.ctrlKey) parts.push("CTRL")
    if (event.altKey) parts.push("ALT")
    if (event.metaKey) parts.push("META")
    if (event.shiftKey && (special || hasCommandModifier)) parts.push("SHIFT")
    parts.push(key)
    event.preventDefault()
    this.queueAction({ type: "key", keys: parts })
  }

  private onTextSubmit(event: SubmitEvent): void {
    event.preventDefault()
    const input = this.root.querySelector<HTMLInputElement>("[data-role=desktop-text]")
    if (!input || !input.value || input.disabled) return
    const text = input.value
    input.value = ""
    this.queueAction({ type: "type", text })
  }
}
