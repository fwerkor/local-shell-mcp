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
  keys?: string
}

type Point = { x: number; y: number }

type PointerStart = {
  point: Point
  bounds: GuiBounds
  clientX: number
  clientY: number
  pointerId: number
}

export const SINGLE_CLICK_DELAY_MS = 500

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
  private loadingWindows = false
  private framePromise: Promise<void> | null = null
  private frameRequestKey = ""
  private frameAbort: AbortController | null = null
  private frameUrl = ""
  private frameBounds: GuiBounds | null = null
  private frameEpoch = 0
  private actionQueue: Promise<void> = Promise.resolve()
  private pendingActions = 0
  private pointerStart: PointerStart | null = null
  private suppressClickUntil = 0
  private clickTimer: number | null = null
  private wheelTimer: number | null = null
  private wheelDelta = 0
  private wheelPoint: Point | null = null
  private wheelBounds: GuiBounds | null = null

  constructor(context: NativePageContext) {
    super(context)
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
    this.listen(this.root, "contextmenu", (event) => this.onContextMenu(event as MouseEvent))
    this.listen(this.root, "wheel", (event) => this.onWheel(event as WheelEvent), { passive: false })
    this.listen(this.root, "keydown", (event) => this.onKeyDown(event as KeyboardEvent))
    const form = this.root.querySelector<HTMLFormElement>("[data-role=desktop-text-form]")
    if (form) this.listen(form, "submit", (event) => this.onTextSubmit(event as SubmitEvent))

    this.every(() => {
      if (!this.destroyed && this.selectedWindowId && this.pendingActions === 0) void this.refreshFrame()
    }, 1000)
    this.every(() => {
      if (!this.destroyed && !this.loadingWindows) void this.refreshWindows(false)
    }, 5000)
    void this.refresh()
  }

  async refresh(): Promise<void> {
    await this.refreshWindows(true)
  }

  override destroy(): void {
    this.frameEpoch += 1
    this.frameAbort?.abort()
    this.frameAbort = null
    if (this.clickTimer !== null) window.clearTimeout(this.clickTimer)
    if (this.wheelTimer !== null) window.clearTimeout(this.wheelTimer)
    this.revokeFrame()
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
      this.clearFrame()
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
    if (scale) scale.textContent = this.frameBounds ? "1:1 logical" : "—"
    if (connection) {
      connection.classList.toggle("error", error)
      connection.classList.toggle("online", Boolean(current && this.frameBounds && !error))
      const label = connection.querySelector<HTMLElement>("strong")
      if (label) label.textContent = error ? "Unavailable" : current ? this.frameBounds ? "Live" : "Connecting" : "Idle"
    }
    const enabled = Boolean(current && this.frameBounds)
    if (text) text.disabled = !enabled
    if (submit) submit.disabled = !enabled
  }

  private async refreshWindows(forceFrame: boolean): Promise<void> {
    if (this.loadingWindows) return
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
      if (!this.windows.some((window) => window.id === previous)) {
        this.selectedWindowId = this.windows[0]?.id || ""
        this.clearFrame()
      }
      this.renderSelectors()
      if (this.selectedWindowId && (forceFrame || !this.frameBounds)) await this.refreshFrame()
    } catch (error) {
      if (requestedMachine !== this.machine) return
      this.windows = []
      this.selectedWindowId = ""
      this.clearFrame()
      this.renderSelectors()
      this.renderStatus(error instanceof Error ? error.message : String(error), true)
    } finally {
      this.loadingWindows = false
    }
  }

  private refreshFrame(): Promise<void> {
    const key = `${this.machine}\0${this.selectedWindowId}`
    if (this.framePromise && this.frameRequestKey === key) return this.framePromise
    if (this.framePromise && this.frameRequestKey !== key) this.frameAbort?.abort()

    const controller = new AbortController()
    this.frameAbort = controller
    this.frameRequestKey = key
    const promise = this.loadFrame(key, controller).finally(() => {
      if (this.framePromise === promise) {
        this.framePromise = null
        this.frameAbort = null
        this.frameRequestKey = ""
      }
    })
    this.framePromise = promise
    return promise
  }

  private async loadFrame(requestKey: string, controller: AbortController): Promise<void> {
    const windowId = this.selectedWindowId
    if (!windowId) {
      this.clearFrame()
      return
    }
    const requestedMachine = this.machine
    const epoch = ++this.frameEpoch
    const search = queryString({ machine: requestedMachine, window_id: windowId })
    const headers: HeadersInit = { Accept: "image/png,image/jpeg,image/webp,*/*" }
    const token = this.context.accessToken()
    if (token) headers.Authorization = `Bearer ${token}`
    try {
      const response = await fetch(`${this.context.apiPrefix || "/api/ui"}/gui/frame${search}`, {
        headers,
        cache: "no-store",
        credentials: "omit",
        signal: controller.signal,
      })
      if (!response.ok) {
        let message = `GUI frame returned HTTP ${response.status}`
        try {
          const payload = await response.json() as { message?: string }
          if (payload.message) message = payload.message
        } catch {
          // Keep the HTTP error.
        }
        throw new Error(message)
      }
      const bounds: GuiBounds = {
        x: numericHeader(response, "X-LSM-GUI-Window-X"),
        y: numericHeader(response, "X-LSM-GUI-Window-Y"),
        width: numericHeader(response, "X-LSM-GUI-Window-Width"),
        height: numericHeader(response, "X-LSM-GUI-Window-Height"),
      }
      if (!bounds.width || !bounds.height) throw new Error("GUI frame returned invalid window bounds")
      const blob = await response.blob()
      if (
        this.destroyed
        || controller.signal.aborted
        || requestKey !== this.frameRequestKey
        || epoch !== this.frameEpoch
        || requestedMachine !== this.machine
        || windowId !== this.selectedWindowId
      ) return
      const nextUrl = URL.createObjectURL(blob)
      const previousUrl = this.frameUrl
      this.frameUrl = nextUrl
      this.frameBounds = bounds
      const image = this.root.querySelector<HTMLImageElement>("[data-role=desktop-frame]")
      const placeholder = this.root.querySelector<HTMLElement>("[data-role=desktop-placeholder]")
      if (image) {
        image.src = nextUrl
        image.hidden = false
      }
      if (placeholder) placeholder.hidden = true
      if (previousUrl) URL.revokeObjectURL(previousUrl)
      this.renderStatus()
    } catch (error) {
      if (
        controller.signal.aborted
        || requestKey !== this.frameRequestKey
        || epoch !== this.frameEpoch
        || requestedMachine !== this.machine
        || windowId !== this.selectedWindowId
      ) return
      const message = error instanceof Error ? error.message : String(error)
      this.clearFrame()
      this.renderStatus(message, true)
    }
  }

  private clearFrame(): void {
    this.frameEpoch += 1
    this.frameAbort?.abort()
    this.frameAbort = null
    this.frameRequestKey = ""
    this.frameBounds = null
    this.revokeFrame()
    const image = this.root?.querySelector<HTMLImageElement>("[data-role=desktop-frame]")
    const placeholder = this.root?.querySelector<HTMLElement>("[data-role=desktop-placeholder]")
    if (image) {
      image.hidden = true
      image.removeAttribute("src")
    }
    if (placeholder) placeholder.hidden = false
  }

  private revokeFrame(): void {
    if (!this.frameUrl) return
    URL.revokeObjectURL(this.frameUrl)
    this.frameUrl = ""
  }

  private pointForEvent(event: MouseEvent): Point | null {
    const image = this.root.querySelector<HTMLImageElement>("[data-role=desktop-frame]")
    const bounds = this.frameBounds
    if (!image || image.hidden || !bounds?.width || !bounds.height) return null
    return framePoint(event.clientX, event.clientY, image.getBoundingClientRect(), bounds)
  }

  private queueAction(action: GuiAction, observedBounds?: GuiBounds): void {
    const windowId = this.selectedWindowId
    const machine = this.machine
    const bounds = observedBounds ? { ...observedBounds } : this.frameBounds ? { ...this.frameBounds } : null
    if (!windowId || !bounds) return

    this.pendingActions += 1
    this.renderInputPulse()
    const run = async () => {
      try {
        await this.context.api.send("/gui/action", "POST", {
          machine,
          window_id: windowId,
          bounds,
          actions: [action],
        })
        if (machine === this.machine && windowId === this.selectedWindowId) {
          void this.refreshFrame()
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        this.context.notify(`Desktop input: ${message}`, "error")
        if (
          machine === this.machine
          && windowId === this.selectedWindowId
          && /moved|resized|no longer available|stale/i.test(message)
        ) {
          await this.refreshWindows(true)
        }
      } finally {
        this.pendingActions = Math.max(0, this.pendingActions - 1)
        this.renderInputPulse()
      }
    }
    this.actionQueue = this.actionQueue.then(run, run)
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
      this.clearFrame()
      this.renderSelectors()
      void this.refreshWindows(true)
      return
    }
    if (target.dataset.role === "desktop-window") {
      if (target.value === this.selectedWindowId) return
      this.selectedWindowId = target.value
      this.clearFrame()
      this.renderSelectors()
      void this.refreshFrame()
    }
  }

  private onClick(event: MouseEvent): void {
    const actionTarget = (event.target as HTMLElement).closest<HTMLElement>("[data-action]")
    if (actionTarget?.dataset.action === "desktop-refresh-windows") {
      void this.refreshWindows(true)
      return
    }
    if (actionTarget?.dataset.action === "desktop-refresh-frame") {
      void this.refreshFrame()
      return
    }

    const image = (event.target as HTMLElement).closest<HTMLImageElement>("[data-role=desktop-frame]")
    if (!image || event.button !== 0 || Date.now() < this.suppressClickUntil) return
    const point = this.pointForEvent(event)
    const observedBounds = this.frameBounds ? { ...this.frameBounds } : null
    if (!point || !observedBounds) return
    this.root.querySelector<HTMLElement>("[data-role=desktop-stage]")?.focus({ preventScroll: true })
    if (event.detail >= 2) {
      if (this.clickTimer !== null) {
        window.clearTimeout(this.clickTimer)
        this.clickTimer = null
      }
      this.queueAction({ type: "double_click", ...point }, observedBounds)
      return
    }
    if (this.clickTimer !== null) window.clearTimeout(this.clickTimer)
    this.clickTimer = window.setTimeout(() => {
      this.clickTimer = null
      this.queueAction({ type: "click", ...point }, observedBounds)
    }, SINGLE_CLICK_DELAY_MS)
  }

  private onPointerDown(event: PointerEvent): void {
    if (event.button !== 0) return
    const image = (event.target as HTMLElement).closest<HTMLImageElement>("[data-role=desktop-frame]")
    if (!image) return
    const point = this.pointForEvent(event)
    const bounds = this.frameBounds ? { ...this.frameBounds } : null
    if (!point || !bounds) return
    this.pointerStart = {
      point,
      bounds,
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
    }, start.bounds)
  }

  private onContextMenu(event: MouseEvent): void {
    const image = (event.target as HTMLElement).closest<HTMLImageElement>("[data-role=desktop-frame]")
    if (!image) return
    const point = this.pointForEvent(event)
    if (!point) return
    event.preventDefault()
    this.root.querySelector<HTMLElement>("[data-role=desktop-stage]")?.focus({ preventScroll: true })
    this.queueAction({ type: "right_click", ...point })
  }

  private onWheel(event: WheelEvent): void {
    const image = (event.target as HTMLElement).closest<HTMLImageElement>("[data-role=desktop-frame]")
    if (!image) return
    const point = this.pointForEvent(event)
    if (!point) return
    event.preventDefault()
    this.wheelDelta += event.deltaY
    this.wheelPoint = point
    this.wheelBounds = this.frameBounds ? { ...this.frameBounds } : null
    if (this.wheelTimer !== null) window.clearTimeout(this.wheelTimer)
    this.wheelTimer = window.setTimeout(() => {
      this.wheelTimer = null
      const delta = this.wheelDelta
      const target = this.wheelPoint
      const observedBounds = this.wheelBounds
      this.wheelDelta = 0
      this.wheelPoint = null
      this.wheelBounds = null
      if (!target || !observedBounds || !delta) return
      const amount = wheelScrollAmount(delta)
      if (amount) this.queueAction({ type: "scroll", ...target, delta_y: amount }, observedBounds)
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

    const key = special || (event.key.length === 1 ? event.key.toUpperCase() : "")
    if (!key) return
    const parts: string[] = []
    if (event.ctrlKey) parts.push("CTRL")
    if (event.altKey) parts.push("ALT")
    if (event.metaKey) parts.push("META")
    if (event.shiftKey && (special || hasCommandModifier)) parts.push("SHIFT")
    parts.push(key)
    event.preventDefault()
    this.queueAction({ type: "key", keys: parts.join("+") })
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
