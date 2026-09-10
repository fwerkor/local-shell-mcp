import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import { TerminalWriteBuffer, type TerminalWriteChunk } from "../terminal-write-buffer"
import type { TerminalPayload, TerminalSession } from "../types"
import {
  BaseController,
  button,
  confirmDialog,
  copyText,
  encoder,
  escapeHtml,
  formatDate,
  openFormDialog,
  queryString,
  type NativePageContext,
} from "./common"

export class TerminalsController extends BaseController {
  private machine = "local"
  private sessions: TerminalSession[] = []
  private selectedSessionId: string | null = null
  private terminal: Terminal | null = null
  private terminalWrites: TerminalWriteBuffer | null = null
  private fitAddon: FitAddon | null = null
  private socket: WebSocket | null = null
  private resizeObserver: ResizeObserver | null = null
  private reconnectTimer: number | null = null
  private reconnectAttempt = 0
  private manualClose = false
  private loading = false
  private refreshQueued = false
  private loadedMachine: string | null = null
  private scrollbackSupported = false
  private scrollbackHistory = 0
  private scrollbackPosition = 0
  private scrollRequestTimer: number | null = null
  private scrollbackSyncTimer: number | null = null
  private pendingScrollPosition: number | null = null
  private scrollRequestInFlight: number | null = null
  private scrollRequestSequence = 0
  private history: string[] = []
  private historyIndex = 0
  private lastSearch = ""
  private lastSearchLine = 0
  private sessionQuery = ""
  private sidebarVisible = true
  private fontSize = 14

  mount(root: HTMLElement): void {
    this.root = root
    this.machine = this.context.machines().some((item) => item.name === "local") ? "local" : this.context.machines()[0]?.name || "local"
    this.root.innerHTML = `<section class="native-page terminals-page">
      <div class="native-toolbar terminal-toolbar">
        <div class="toolbar-group"><label>Machine<select data-role="terminal-machine"></select></label><span class="connection-pill connecting" data-role="connection"><i></i><strong>Loading…</strong></span><span class="terminal-dimensions" data-role="dimensions">—</span></div>
        <div class="toolbar-actions">${button("New", "new-session", { icon: "+", primary: true })}${button("Kill", "kill-session", { danger: true, disabled: true })}${button("Reconnect", "reconnect", { icon: "↻" })}${button("Sessions", "toggle-sidebar")}${button("A−", "font-down")}${button("A+", "font-up")}</div>
      </div>
      <div class="terminal-layout" data-role="terminal-workspace">
        <aside class="native-panel terminal-sessions"><header><div><h3>Sessions</h3><p data-role="session-summary">Loading…</p></div><div class="terminal-session-switch"><button type="button" data-action="previous-session" aria-label="Previous session">‹</button><button type="button" data-action="next-session" aria-label="Next session">›</button></div></header><label class="terminal-session-search"><span>⌕</span><input data-role="session-search" type="search" placeholder="Filter sessions"/></label><div class="session-list" data-role="sessions"></div></aside>
        <section class="native-panel terminal-stage-panel"><header><div><h3 data-role="terminal-title">Persistent terminal</h3><p data-role="terminal-subtitle">Loading terminals…</p></div><div class="terminal-stage-actions">${button("Copy", "copy")}${button("Paste", "paste")}${button("Find", "search")}${button("Clear", "clear")}${button("Fullscreen", "fullscreen")}<div class="terminal-search" data-role="search-box" hidden><input data-role="search-input" placeholder="Find in terminal"/><button type="button" data-action="search-prev">Previous</button><button type="button" data-action="search-next">Next</button><button type="button" data-action="search-close">Close</button></div></div></header><div class="persistent-terminal" data-role="terminal"></div><div class="terminal-scrollbar unsupported" data-role="scrollbar" role="scrollbar" tabindex="0" aria-label="Terminal scrollback" aria-valuemin="0" aria-valuemax="0" aria-valuenow="0"><div class="terminal-scrollbar-spacer"></div></div><div class="terminal-overlay" data-role="terminal-overlay">Loading terminals…</div><nav class="terminal-touchbar"><button type="button" data-sequence="\u001b">Esc</button><button type="button" data-sequence="\t">Tab</button><button type="button" data-sequence="\u001b[D">←</button><button type="button" data-sequence="\u001b[A">↑</button><button type="button" data-sequence="\u001b[B">↓</button><button type="button" data-sequence="\u001b[C">→</button><button type="button" data-sequence="\r">Enter</button><button type="button" data-sequence="\u0003">Ctrl-C</button></nav><form class="command-dock" data-role="command-form"><div class="command-signals"><button type="button" data-sequence="\u0003" title="Interrupt">^C</button><button type="button" data-sequence="\u0004" title="End of input">^D</button><button type="button" data-sequence="\u001a" title="Suspend">^Z</button></div><input data-role="command-input" autocomplete="off" placeholder="Send a command to the attached session"/><button class="native-button primary" type="submit">Send</button></form></section>
      </div>
    </section>`
    this.renderMachineSelect()
    this.showLoadingState()
    this.initializeTerminal()
    this.listen(root, "click", (event) => this.onClick(event))
    this.listen(root, "change", (event) => this.onChange(event))
    this.listen(root, "input", (event) => this.onInput(event))
    this.listen(root, "submit", (event) => this.onSubmit(event))
    this.listen(root, "keydown", (event) => this.onRootKeyDown(event as KeyboardEvent))
    this.every(() => void this.refresh(), 4_000)
    void this.refresh()
  }

  private renderMachineSelect(): void {
    const select = this.root.querySelector<HTMLSelectElement>("[data-role=terminal-machine]")
    if (!select) return
    select.innerHTML = this.context.machines().map((machine) => `<option value="${escapeHtml(machine.name)}"${machine.name === this.machine ? " selected" : ""}>${escapeHtml(machine.name)}</option>`).join("")
  }

  private initializeTerminal(): void {
    const host = this.root.querySelector<HTMLElement>("[data-role=terminal]")!
    this.terminal = new Terminal({
      allowTransparency: true,
      convertEol: false,
      cursorBlink: true,
      cursorStyle: "bar",
      fontFamily: '"JetBrains Mono", "Cascadia Code", "SFMono-Regular", Consolas, monospace',
      fontSize: this.fontSize,
      lineHeight: 1.12,
      scrollback: 12_000,
      smoothScrollDuration: 70,
      theme: {
        background: "rgba(0,0,0,0)", foreground: "#e7edf8", cursor: "#8b7cf6", selectionBackground: "#53648699",
        black: "#0b1020", red: "#f7768e", green: "#8bd49c", yellow: "#e0af68", blue: "#7aa2f7", magenta: "#bb9af7", cyan: "#65d1c5", white: "#e7edf8",
        brightBlack: "#6b7890", brightRed: "#ff9cab", brightGreen: "#a8e6b4", brightYellow: "#f3cc85", brightBlue: "#a4c2ff", brightMagenta: "#d5b9ff", brightCyan: "#92eee4", brightWhite: "#ffffff",
      },
    })
    this.fitAddon = new FitAddon()
    this.terminal.loadAddon(this.fitAddon)
    this.terminal.open(host)
    this.terminalWrites = new TerminalWriteBuffer((chunk) => this.terminal?.write(chunk), {
      onOverflow: () => {
        this.terminal?.scrollToBottom()
        this.context.notify("Terminal output resumed after the history buffer filled.", "info")
      },
    })
    this.terminal.onData((data) => this.sendRaw(data))
    this.terminal.onScroll((viewportY) => {
      const terminal = this.terminal
      if (!terminal) return
      this.terminalWrites?.setHeld(viewportY < terminal.buffer.active.baseY)
    })
    this.terminal.attachCustomKeyEventHandler((event) => {
      if (event.type === "keydown" && event.key === "PageUp") this.terminalWrites?.setHeld(true)
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "c") {
        if (event.type === "keydown") void this.copySelection()
        return false
      }
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "v") {
        if (event.type === "keydown") void this.pasteClipboard()
        return false
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
        if (event.type === "keydown") this.openSearch()
        return false
      }
      return true
    })
    this.resizeObserver = new ResizeObserver(() => window.requestAnimationFrame(() => this.fit()))
    this.resizeObserver.observe(host)
    this.listen(host, "wheel", (event) => this.onTerminalWheel(event as WheelEvent), { capture: true, passive: false })
    const scrollbar = this.root.querySelector<HTMLElement>("[data-role=scrollbar]")
    if (scrollbar) {
      this.listen(scrollbar, "scroll", () => this.onScrollbarScroll())
      this.listen(scrollbar, "keydown", (event) => this.onScrollbarKeyDown(event as KeyboardEvent))
    }
    window.requestAnimationFrame(() => this.fit())
  }

  async refresh(): Promise<void> {
    if (this.loading) {
      this.refreshQueued = true
      return
    }
    this.loading = true
    const machines = this.context.machines()
    if (!machines.some((machine) => machine.name === this.machine)) {
      this.disconnect(false)
      this.machine = machines.some((machine) => machine.name === "local") ? "local" : machines[0]?.name || "local"
      this.sessions = []
      this.selectedSessionId = null
      this.loadedMachine = null
      this.terminalWrites?.clear()
      this.terminalWrites?.setHeld(false)
      this.terminal?.clear()
      this.showLoadingState()
    }
    this.renderMachineSelect()
    const requestedMachine = this.machine
    try {
      const payload = await this.context.api.get<TerminalPayload>(`/terminals${queryString({ machine: requestedMachine })}`)
      if (this.destroyed || requestedMachine !== this.machine || payload.machine !== requestedMachine) return
      this.sessions = payload.sessions
      this.loadedMachine = requestedMachine
      const previous = this.selectedSessionId
      if (!previous || !this.sessions.some((session) => session.session_id === previous)) this.selectedSessionId = this.sessions[0]?.session_id || null
      this.renderSessions()
      if (this.selectedSessionId && this.selectedSessionId !== previous) this.connect()
      if (!this.selectedSessionId) this.disconnect(true)
    } catch (error) {
      if (this.destroyed || requestedMachine !== this.machine) return
      this.context.notify(`Terminals: ${error instanceof Error ? error.message : String(error)}`, "error")
      if (this.loadedMachine !== requestedMachine) this.showLoadError(error)
    } finally {
      this.loading = false
      if (this.refreshQueued && !this.destroyed) {
        this.refreshQueued = false
        void this.refresh()
      }
    }
  }

  private showLoadingState(): void {
    const list = this.root.querySelector<HTMLElement>("[data-role=sessions]")
    const summary = this.root.querySelector<HTMLElement>("[data-role=session-summary]")
    const title = this.root.querySelector<HTMLElement>("[data-role=terminal-title]")
    const subtitle = this.root.querySelector<HTMLElement>("[data-role=terminal-subtitle]")
    if (list) list.innerHTML = '<div class="native-loading">Loading terminals…</div>'
    if (summary) summary.textContent = "Loading…"
    if (title) title.textContent = "Persistent terminal"
    if (subtitle) subtitle.textContent = "Loading terminals…"
    for (const action of ["kill-session", "previous-session", "next-session", "reconnect", "copy", "paste", "search", "clear"]) {
      const control = this.root.querySelector<HTMLButtonElement>(`[data-action=${action}]`)
      if (control) control.disabled = true
    }
    this.setConnection("connecting", "Loading…")
  }

  private showLoadError(error: unknown): void {
    const detail = error instanceof Error ? error.message : String(error)
    const list = this.root.querySelector<HTMLElement>("[data-role=sessions]")
    const summary = this.root.querySelector<HTMLElement>("[data-role=session-summary]")
    if (list) list.innerHTML = `<div class="native-error">${escapeHtml(detail || "Unable to load terminals")}</div>`
    if (summary) summary.textContent = "Load failed"
    this.setConnection("error", "Load failed")
  }

  private renderSessions(): void {
    const list = this.root.querySelector<HTMLElement>("[data-role=sessions]")
    const summary = this.root.querySelector<HTMLElement>("[data-role=session-summary]")
    const kill = this.root.querySelector<HTMLButtonElement>("[data-action=kill-session]")
    const previous = this.root.querySelector<HTMLButtonElement>("[data-action=previous-session]")
    const next = this.root.querySelector<HTMLButtonElement>("[data-action=next-session]")
    const visibleSessions = this.visibleSessions()
    const hasSession = Boolean(this.selectedSessionId)
    if (summary) summary.textContent = `${this.sessions.length} persistent session${this.sessions.length === 1 ? "" : "s"}`
    if (kill) kill.disabled = !hasSession
    if (previous) previous.disabled = visibleSessions.length < 2
    if (next) next.disabled = visibleSessions.length < 2
    for (const action of ["reconnect", "copy", "paste", "search", "clear"]) {
      const control = this.root.querySelector<HTMLButtonElement>(`[data-action=${action}]`)
      if (control) control.disabled = !hasSession
    }
    if (!list) return
    if (!visibleSessions.length) {
      if (this.sessions.length) {
        list.innerHTML = '<div class="native-empty"><strong>No matches</strong><span>Try a different session filter.</span></div>'
        this.updateTerminalHeader()
        return
      }
      list.innerHTML = '<div class="native-empty"><strong>No sessions</strong><span>Create one to start working.</span></div>'
      this.updateTerminalHeader()
      return
    }
    list.innerHTML = visibleSessions.map((session) => `<button type="button" class="session-row ${session.session_id === this.selectedSessionId ? "active" : ""}" data-session="${escapeHtml(session.session_id)}"><span class="session-state"></span><span><strong>${escapeHtml(session.session_id)}</strong><small>${escapeHtml(session.backend || "persistent shell")} · attached ${escapeHtml(String(session.attached ?? "—"))}</small></span></button>`).join("")
    this.updateTerminalHeader()
  }

  private updateTerminalHeader(): void {
    const session = this.sessions.find((item) => item.session_id === this.selectedSessionId)
    const title = this.root.querySelector<HTMLElement>("[data-role=terminal-title]")
    const subtitle = this.root.querySelector<HTMLElement>("[data-role=terminal-subtitle]")
    if (title) title.textContent = session?.session_id || "Persistent terminal"
    if (subtitle) subtitle.textContent = session ? `${this.machine} · ${session.backend || "shell"} · created ${formatDate(session.created)}` : "Select or create a session"
  }

  private setConnection(state: "idle" | "connecting" | "connected" | "error", label: string): void {
    const element = this.root.querySelector<HTMLElement>("[data-role=connection]")
    if (!element) return
    element.className = `connection-pill ${state}`
    const strong = element.querySelector("strong")
    if (strong) strong.textContent = label
    const overlay = this.root.querySelector<HTMLElement>("[data-role=terminal-overlay]")
    if (overlay) {
      overlay.hidden = state === "connected"
      overlay.textContent = label
    }
  }

  private protocols(): string[] {
    const protocols = ["lsm-ui"]
    const token = this.context.accessToken()
    if (token) {
      let binary = ""
      for (const byte of encoder.encode(token)) binary += String.fromCharCode(byte)
      protocols.push(`bearer.${btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}`)
    }
    return protocols
  }

  private connect(): void {
    const sessionId = this.selectedSessionId
    if (!sessionId || !this.terminal) return
    this.disconnect(false)
    this.manualClose = false
    this.setConnection("connecting", "Connecting")
    this.terminalWrites?.clear()
    this.terminalWrites?.setHeld(false)
    this.terminal.clear()
    this.terminal.write(`\x1b[38;2;139;124;246mAttaching to ${this.machine}:${sessionId}…\x1b[0m\r\n`)
    this.fit()
    const scheme = location.protocol === "https:" ? "wss:" : "ws:"
    const url = new URL(`${scheme}//${location.host}${this.context.uiPath}/ws/shell`)
    url.searchParams.set("machine", this.machine)
    url.searchParams.set("session_id", sessionId)
    url.searchParams.set("cols", String(this.terminal.cols))
    url.searchParams.set("rows", String(this.terminal.rows))
    url.searchParams.set("scrollback", "1")
    const socket = new WebSocket(url, this.protocols())
    socket.binaryType = "arraybuffer"
    this.socket = socket
    socket.onopen = () => {
      if (this.socket !== socket) return
      this.reconnectAttempt = 0
      this.setConnection("connected", "Connected")
      this.fit()
      this.terminal?.focus()
    }
    socket.onmessage = async (event) => {
      if (this.socket !== socket || !this.terminal) return
      if (typeof event.data === "string" && this.handleSocketControl(event.data)) return
      const data = event.data instanceof ArrayBuffer
        ? new Uint8Array(event.data)
        : event.data instanceof Blob
          ? new Uint8Array(await event.data.arrayBuffer())
          : String(event.data)
      if (this.socket === socket) this.writeTerminalData(data)
    }
    socket.onerror = () => {
      if (this.socket === socket) this.setConnection("error", "Connection error")
    }
    socket.onclose = (event) => {
      if (this.socket !== socket) return
      this.socket = null
      if (this.manualClose) return
      if ([4401, 4408, 4429, 1011].includes(event.code)) {
        this.setConnection("error", event.reason || "Disconnected")
        return
      }
      if (event.code === 4411) {
        this.setConnection("error", "Attachment interrupted")
        this.scheduleReconnect()
        return
      }
      this.scheduleReconnect()
    }
  }

  private writeTerminalData(data: TerminalWriteChunk): void {
    this.terminalWrites?.write(data)
  }

  private handleSocketControl(value: string): boolean {
    let payload: Record<string, unknown>
    try {
      payload = JSON.parse(value) as Record<string, unknown>
    } catch {
      return false
    }
    const requestId = typeof payload.request_id === "number" && Number.isFinite(payload.request_id) ? Math.floor(payload.request_id) : null
    if (payload.type === "scrollback-ack") {
      if (requestId !== null && requestId === this.scrollRequestInFlight) {
        this.scrollRequestInFlight = null
        if (this.pendingScrollPosition !== null) this.scheduleScrollRequest(0)
      }
      return true
    }
    if (payload.type !== "scrollback") return false
    const supported = payload.supported === true
    const history = typeof payload.history === "number" && Number.isFinite(payload.history) ? Math.max(0, Math.floor(payload.history)) : 0
    const position = typeof payload.position === "number" && Number.isFinite(payload.position) ? Math.max(0, Math.floor(payload.position)) : 0
    this.scrollbackSupported = supported
    this.scrollbackHistory = history
    const pending = this.pendingScrollPosition
    this.scrollbackPosition = pending === null ? Math.min(position, history) : Math.min(pending, history)
    if (requestId !== null && requestId === this.scrollRequestInFlight) {
      this.scrollRequestInFlight = null
      if (this.pendingScrollPosition !== null) this.scheduleScrollRequest(0)
    }
    this.renderScrollbar()
    return true
  }

  private renderScrollbar(): void {
    const scrollbar = this.root.querySelector<HTMLElement>("[data-role=scrollbar]")
    if (!scrollbar) return
    const stage = this.root.querySelector<HTMLElement>(".terminal-stage-panel")
    stage?.classList.toggle("tmux-scrollback", this.scrollbackSupported)
    scrollbar.classList.toggle("unsupported", !this.scrollbackSupported)
    scrollbar.classList.toggle("empty", this.scrollbackHistory <= 0)
    scrollbar.style.setProperty("--scrollback-history", `${this.scrollbackHistory}px`)
    scrollbar.setAttribute("aria-valuemax", String(this.scrollbackHistory))
    scrollbar.setAttribute("aria-valuenow", String(this.scrollbackPosition))
    scrollbar.setAttribute("aria-valuetext", this.scrollbackPosition > 0 ? `${this.scrollbackPosition} lines from bottom` : "Bottom")
    const target = Math.max(0, this.scrollbackHistory - this.scrollbackPosition)
    if (Math.abs(scrollbar.scrollTop - target) > 0.5) scrollbar.scrollTop = target
  }

  private queueScrollRequest(position: number): void {
    if (!this.scrollbackSupported || this.socket?.readyState !== WebSocket.OPEN) return
    this.pendingScrollPosition = Math.max(0, Math.min(position, this.scrollbackHistory))
    if (this.scrollRequestInFlight !== null) return
    this.scheduleScrollRequest(40)
  }

  private scheduleScrollRequest(delay: number): void {
    if (this.scrollRequestTimer !== null || this.scrollRequestInFlight !== null) return
    this.scrollRequestTimer = window.setTimeout(() => {
      this.scrollRequestTimer = null
      const socket = this.socket
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        this.pendingScrollPosition = null
        return
      }
      if (this.pendingScrollPosition === null) return
      const requestId = ++this.scrollRequestSequence
      const payload = { type: "scrollback", position: this.pendingScrollPosition, request_id: requestId }
      this.pendingScrollPosition = null
      this.scrollRequestInFlight = requestId
      socket.send(JSON.stringify(payload))
    }, delay)
  }

  private onScrollbarScroll(): void {
    if (!this.scrollbackSupported) return
    const scrollbar = this.root.querySelector<HTMLElement>("[data-role=scrollbar]")
    if (!scrollbar) return
    const position = Math.max(0, Math.min(this.scrollbackHistory - Math.round(scrollbar.scrollTop), this.scrollbackHistory))
    if (position === this.scrollbackPosition) return
    this.scrollbackPosition = position
    scrollbar.setAttribute("aria-valuenow", String(position))
    scrollbar.setAttribute("aria-valuetext", position > 0 ? `${position} lines from bottom` : "Bottom")
    this.queueScrollRequest(position)
  }

  private onTerminalWheel(event: WheelEvent): void {
    const terminal = this.terminal
    if (!this.scrollbackSupported || !terminal || event.deltaY === 0) return
    if (terminal.modes.mouseTrackingMode !== "none") {
      this.queueScrollbackSync()
      return
    }
    event.preventDefault()
    event.stopPropagation()
    const magnitude = Math.max(1, Math.min(24, Math.ceil(Math.abs(event.deltaY) / 24)))
    const scrollbar = this.root.querySelector<HTMLElement>("[data-role=scrollbar]")
    if (!scrollbar) return
    scrollbar.scrollTop += event.deltaY < 0 ? -magnitude : magnitude
  }

  private onScrollbarKeyDown(event: KeyboardEvent): void {
    if (!this.scrollbackSupported) return
    const page = Math.max(1, this.terminal?.rows ?? 24)
    let position = this.scrollbackPosition
    if (event.key === "ArrowUp") position += 1
    else if (event.key === "ArrowDown") position -= 1
    else if (event.key === "PageUp") position += page
    else if (event.key === "PageDown") position -= page
    else if (event.key === "Home") position = this.scrollbackHistory
    else if (event.key === "End") position = 0
    else return
    event.preventDefault()
    event.stopPropagation()
    position = Math.max(0, Math.min(position, this.scrollbackHistory))
    if (position === this.scrollbackPosition) return
    this.scrollbackPosition = position
    this.renderScrollbar()
    this.queueScrollRequest(position)
  }

  private scheduleReconnect(): void {
    if (this.manualClose || !this.selectedSessionId) return
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer)
    const delay = Math.min(6_000, 400 * 2 ** this.reconnectAttempt)
    this.reconnectAttempt += 1
    this.setConnection("connecting", `Reconnecting in ${(delay / 1000).toFixed(1)}s`)
    this.reconnectTimer = window.setTimeout(() => this.connect(), delay)
  }

  private disconnect(manual: boolean): void {
    this.manualClose = manual
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    if (this.scrollRequestTimer !== null) window.clearTimeout(this.scrollRequestTimer)
    this.scrollRequestTimer = null
    if (this.scrollbackSyncTimer !== null) window.clearTimeout(this.scrollbackSyncTimer)
    this.scrollbackSyncTimer = null
    this.pendingScrollPosition = null
    this.scrollRequestInFlight = null
    const socket = this.socket
    this.socket = null
    socket?.close()
    this.scrollbackSupported = false
    this.scrollbackHistory = 0
    this.scrollbackPosition = 0
    this.renderScrollbar()
    if (manual) this.setConnection("idle", this.selectedSessionId ? "Disconnected" : "No session")
  }

  private fit(): void {
    if (!this.terminal || !this.fitAddon) return
    try {
      this.fitAddon.fit()
    } catch {
      return
    }
    const dimensions = this.root.querySelector<HTMLElement>("[data-role=dimensions]")
    if (dimensions) dimensions.textContent = `${this.terminal.cols} × ${this.terminal.rows}`
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: "resize", cols: this.terminal.cols, rows: this.terminal.rows }))
  }

  private sendRaw(value: string): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(encoder.encode(value))
  }

  private queueScrollbackSync(): void {
    if (!this.scrollbackSupported || this.socket?.readyState !== WebSocket.OPEN) return
    if (this.scrollbackSyncTimer !== null) return
    const socket = this.socket
    this.scrollbackSyncTimer = window.setTimeout(() => {
      this.scrollbackSyncTimer = null
      if (this.socket !== socket || socket.readyState !== WebSocket.OPEN) return
      socket.send(JSON.stringify({ type: "scrollback-sync" }))
    }, 0)
  }

  private async createSession(): Promise<void> {
    const values = await openFormDialog({
      title: "New persistent terminal",
      detail: `Start on ${this.machine}`,
      fields: [
        { name: "name", label: "Name", placeholder: "build-shell", help: "Optional. A unique name is generated when empty." },
        { name: "cwd", label: "Working directory", value: ".", required: true },
        { name: "command", label: "Initial command", placeholder: "Optional command to run immediately" },
      ],
      submitLabel: "Start terminal",
    })
    if (!values) return
    try {
      const result = await this.context.api.send<{ session_id: string }>("/terminals/start", "POST", { machine: this.machine, name: values.name.trim() || undefined, cwd: values.cwd.trim() || ".", command: values.command.trim() || undefined })
      this.selectedSessionId = result.session_id
      await this.refresh()
      this.connect()
      this.context.notify(`Started ${result.session_id}`, "success")
      await this.context.refreshChrome()
    } catch (error) {
      this.context.notify(`Start terminal: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private async killSession(): Promise<void> {
    const sessionId = this.selectedSessionId
    if (!sessionId || !await confirmDialog(`Kill ${sessionId}?`, "The persistent terminal and its running foreground process will be terminated.", "Kill session")) return
    try {
      this.disconnect(true)
      await this.context.api.send("/terminals/kill", "POST", { machine: this.machine, session_id: sessionId })
      this.sessions = this.sessions.filter((session) => session.session_id !== sessionId)
      this.selectedSessionId = this.sessions[0]?.session_id || null
      this.renderSessions()
      if (this.selectedSessionId) this.connect()
      else {
        this.terminalWrites?.clear()
        this.terminalWrites?.setHeld(false)
        this.terminal?.clear()
      }
      this.context.notify(`Killed ${sessionId}`, "success")
      await this.context.refreshChrome()
    } catch (error) {
      this.context.notify(`Kill terminal: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private async copySelection(): Promise<void> {
    const selection = this.terminal?.getSelection() || ""
    if (!selection) {
      this.context.notify("Select terminal text before copying.", "info")
      return
    }
    this.context.notify(await copyText(selection) ? "Terminal selection copied" : "Copy failed", "success")
  }

  private async pasteClipboard(): Promise<void> {
    try {
      const text = await navigator.clipboard.readText()
      if (text) this.sendRaw(text)
    } catch (error) {
      this.context.notify(`Paste: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private openSearch(): void {
    const box = this.root.querySelector<HTMLElement>("[data-role=search-box]")
    if (!box) return
    box.hidden = false
    this.root.querySelector<HTMLInputElement>("[data-role=search-input]")?.focus()
  }

  private closeSearch(): void {
    const box = this.root.querySelector<HTMLElement>("[data-role=search-box]")
    if (box) box.hidden = true
    this.terminal?.clearSelection()
    this.terminal?.focus()
  }

  private find(direction: 1 | -1): void {
    if (!this.terminal) return
    const query = this.root.querySelector<HTMLInputElement>("[data-role=search-input]")?.value || ""
    if (!query) return
    const buffer = this.terminal.buffer.active
    if (query !== this.lastSearch) {
      this.lastSearch = query
      this.lastSearchLine = direction > 0 ? buffer.viewportY : buffer.viewportY + this.terminal.rows - 1
    }
    for (let offset = 0; offset < buffer.length; offset += 1) {
      const lineIndex = (this.lastSearchLine + direction * (offset + 1) + buffer.length) % buffer.length
      const line = buffer.getLine(lineIndex)?.translateToString(true) || ""
      const column = direction > 0 ? line.toLowerCase().indexOf(query.toLowerCase()) : line.toLowerCase().lastIndexOf(query.toLowerCase())
      if (column >= 0) {
        this.terminal.select(column, lineIndex, query.length)
        this.terminal.scrollToLine(Math.max(0, lineIndex - Math.floor(this.terminal.rows / 2)))
        this.lastSearchLine = lineIndex
        return
      }
    }
    this.context.notify(`No match for “${query}”`, "info")
  }

  private selectSession(sessionId: string): void {
    if (sessionId === this.selectedSessionId) {
      this.terminal?.focus()
      return
    }
    this.selectedSessionId = sessionId
    this.renderSessions()
    this.connect()
  }

  private visibleSessions(): TerminalSession[] {
    const needle = this.sessionQuery.toLocaleLowerCase()
    return this.sessions.filter((session) => session.session_id.toLocaleLowerCase().includes(needle))
  }

  private switchSession(delta: number): void {
    const sessions = this.visibleSessions()
    if (!sessions.length) return
    const index = sessions.findIndex((session) => session.session_id === this.selectedSessionId)
    const next = index < 0 ? sessions[0] : sessions[(index + delta + sessions.length) % sessions.length]
    if (next) this.selectSession(next.session_id)
  }

  private switchMachine(machine: string): void {
    if (!machine || machine === this.machine) return
    this.disconnect(false)
    this.machine = machine
    this.sessions = []
    this.selectedSessionId = null
    this.loadedMachine = null
    this.terminalWrites?.clear()
    this.terminalWrites?.setHeld(false)
    this.terminal?.clear()
    this.showLoadingState()
    void this.refresh()
  }

  private toggleSidebar(): void {
    this.sidebarVisible = !this.sidebarVisible
    this.root.querySelector("[data-role=terminal-workspace]")?.classList.toggle("sidebar-hidden", !this.sidebarVisible)
    window.requestAnimationFrame(() => this.fit())
  }

  private changeFontSize(delta: number): void {
    this.fontSize = Math.max(10, Math.min(22, this.fontSize + delta))
    if (this.terminal) this.terminal.options.fontSize = this.fontSize
    window.requestAnimationFrame(() => this.fit())
    this.context.notify(`Terminal font ${this.fontSize}px`, "info")
  }

  private onClick(event: MouseEvent): void {
    const target = event.target as HTMLElement
    const sessionId = target.closest<HTMLElement>("[data-session]")?.dataset.session
    if (sessionId) {
      this.selectSession(sessionId)
      return
    }
    const sequence = target.closest<HTMLElement>("[data-sequence]")?.dataset.sequence
    if (sequence !== undefined) {
      this.sendRaw(sequence)
      this.terminal?.focus()
      return
    }
    const action = target.closest<HTMLElement>("[data-action]")?.dataset.action
    if (!action) return
    if (action === "new-session") void this.createSession()
    else if (action === "kill-session") void this.killSession()
    else if (action === "reconnect") this.connect()
    else if (action === "previous-session") this.switchSession(-1)
    else if (action === "next-session") this.switchSession(1)
    else if (action === "toggle-sidebar") this.toggleSidebar()
    else if (action === "font-down") this.changeFontSize(-1)
    else if (action === "font-up") this.changeFontSize(1)
    else if (action === "copy") void this.copySelection()
    else if (action === "paste") void this.pasteClipboard()
    else if (action === "clear") {
      this.terminalWrites?.clear()
      this.terminalWrites?.setHeld(false)
      this.terminal?.clear()
    }
    else if (action === "search") this.openSearch()
    else if (action === "search-prev") this.find(-1)
    else if (action === "search-next") this.find(1)
    else if (action === "search-close") this.closeSearch()
    else if (action === "fullscreen") {
      const workspace = this.root.querySelector<HTMLElement>("[data-role=terminal-workspace]")
      if (document.fullscreenElement) void document.exitFullscreen()
      else if (workspace) void workspace.requestFullscreen()
    }
  }

  private onChange(event: Event): void {
    const target = event.target
    if (target instanceof HTMLSelectElement && target.dataset.role === "terminal-machine") this.switchMachine(target.value)
  }

  private onInput(event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement) || target.dataset.role !== "session-search") return
    this.sessionQuery = target.value
    this.renderSessions()
  }

  private onSubmit(event: SubmitEvent): void {
    const form = event.target
    if (!(form instanceof HTMLFormElement) || form.dataset.role !== "command-form") return
    event.preventDefault()
    const input = form.querySelector<HTMLInputElement>("[data-role=command-input]")
    const command = input?.value || ""
    if (!command || this.socket?.readyState !== WebSocket.OPEN) return
    this.sendRaw(`${command}\r`)
    this.history = [...this.history.filter((item) => item !== command), command].slice(-100)
    this.historyIndex = this.history.length
    if (input) input.value = ""
    this.terminal?.focus()
  }

  private onRootKeyDown(event: KeyboardEvent): void {
    const target = event.target
    if (target instanceof HTMLInputElement && target.dataset.role === "command-input") {
      if (event.key === "ArrowUp") {
        event.preventDefault()
        this.historyIndex = Math.max(0, this.historyIndex - 1)
        target.value = this.history[this.historyIndex] || ""
      } else if (event.key === "ArrowDown") {
        event.preventDefault()
        this.historyIndex = Math.min(this.history.length, this.historyIndex + 1)
        target.value = this.history[this.historyIndex] || ""
      }
      return
    }
    if (target instanceof HTMLInputElement && target.dataset.role === "search-input") {
      if (event.key === "Enter") {
        event.preventDefault()
        this.find(event.shiftKey ? -1 : 1)
      } else if (event.key === "Escape") this.closeSearch()
      return
    }
    if (event.altKey && event.key === "ArrowLeft") {
      event.preventDefault()
      this.switchSession(-1)
    } else if (event.altKey && event.key === "ArrowRight") {
      event.preventDefault()
      this.switchSession(1)
    }
  }

  destroy(): void {
    this.disconnect(true)
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
    this.terminal?.dispose()
    this.terminal = null
    super.destroy()
  }
}

