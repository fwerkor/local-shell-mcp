import "./web-design.scss"
import "./web-native.css"
import "./web.css"
import { mountApplication, mountControllerPage, mountOverview, mountDataPage, unmountReactPage } from "./web-app"
import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import { parseWebClipboardPayload, WEB_CLIPBOARD_OSC } from "./clipboard-protocol"
import { createImageAddon } from "./image-support"
import { browserSelectionShortcut, browserShortcutSequence, TERMINAL_KEY_SEQUENCES } from "./keyboard"
import { measureTerminalCellAspect } from "./terminal-geometry"
import { TerminalWriteBuffer, type TerminalWriteChunk } from "./terminal-write-buffer"
import { visibleWorkloadCount } from "./web-data"
import { hashForView, interfaceModeForView, oauthReturnView, viewFromHash, type WebViewName } from "./web-mode"
import { createNativePage, isNativeView, type NativePageController, type NoticeTone } from "./web-native"
import type { Machine as UiMachine } from "./types"

declare global {
  interface Window {
    __LSM_UI_CONFIG__?: { uiPath?: string; apiPrefix?: string }
  }
  interface Navigator {
    keyboard?: {
      lock?: (keys?: string[]) => Promise<void>
      unlock?: () => void
    }
  }
}

type Health = "healthy" | "attention" | "critical"

type ApiEnvelope<T> = {
  ok: boolean
  message?: string
  error?: string
  data: T
}

type Machine = {
  name?: string
  status?: string
  workdir?: string
  last_seen?: number
  last_seen_age_s?: number
  capabilities?: string[]
  info?: Record<string, unknown>
}

type Job = Record<string, unknown>
type Session = Record<string, unknown>
type Alert = {
  severity?: string
  title?: string
  detail?: string
  node?: string
  age_s?: number
}
type Activity = {
  timestamp?: number
  node?: string
  kind?: string
  title?: string
  detail?: string
}
type BootstrapData = {
  version?: Record<string, unknown>
  machines?: { machines?: Machine[]; counts?: Record<string, number> }
  features?: Record<string, unknown>
}

type DashboardData = {
  generated_at?: number
  health?: Health
  version?: Record<string, unknown>
  system?: Record<string, unknown>
  machines?: { machines?: Machine[]; counts?: Record<string, number> }
  jobs?: Job[]
  job_counts?: Record<string, number>
  sessions?: Session[]
  session_count?: number
  alerts?: Alert[]
  activity?: Activity[]
  audit_total_24h?: number
}

mountApplication()

const UI_PATH = (window.__LSM_UI_CONFIG__?.uiPath || "/ui").replace(/\/$/, "")
const API_PREFIX = (window.__LSM_UI_CONFIG__?.apiPrefix || "/api/ui").replace(/\/$/, "")
const TOKEN_KEY = "lsm.ui.access_token"
const OAUTH_PENDING_KEY = "lsm.ui.oauth_pending"
const encoder = new TextEncoder()

const authGate = document.querySelector<HTMLElement>("#auth-gate")!
const appShell = document.querySelector<HTMLElement>("#app-shell")!
const loginButton = document.querySelector<HTMLButtonElement>("#login-button")!
const loginWebButton = document.querySelector<HTMLButtonElement>("#login-web-button")!
const gateDetail = document.querySelector<HTMLElement>("#gate-detail")!
const viewRoot = document.querySelector<HTMLElement>("#view-root")!
const webView = document.querySelector<HTMLElement>("#web-view")!
const consoleView = document.querySelector<HTMLElement>("#console-view")!
const pageTitle = document.querySelector<HTMLElement>("#page-title")!
const refreshButton = document.querySelector<HTMLButtonElement>("#refresh-button")!
const openConsoleButton = document.querySelector<HTMLButtonElement>("#open-console-button")!
const interfaceButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-interface-mode]"))
const updatedAt = document.querySelector<HTMLElement>("#updated-at")!
const machineNavCount = document.querySelector<HTMLElement>("#machine-nav-count")!
const workloadNavCount = document.querySelector<HTMLElement>("#workload-nav-count")!
const controllerStatus = document.querySelector<HTMLElement>("#controller-status")!
const controllerUptime = document.querySelector<HTMLElement>("#controller-uptime")!
const controllerVersion = document.querySelector<HTMLElement>("#controller-version")!
const controllerOrigin = document.querySelector<HTMLElement>("#controller-origin")!
const footerVersion = document.querySelector<HTMLElement>("#footer-version")!
const footerHealth = document.querySelector<HTMLElement>("#footer-health")!
const footerChecked = document.querySelector<HTMLElement>("#footer-checked")!


let activeView: WebViewName = "overview"
let lastWebView: WebViewName = "overview"
let authenticated = false
let bootstrapData: BootstrapData | null = null
let dashboardData: DashboardData | null = null
let refreshTimer: number | null = null
let callbackView: WebViewName | null = null
let refreshing = false


function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;")
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" && value ? value : fallback
}

function formatDuration(value: unknown): string {
  const seconds = numberValue(value)
  if (seconds === null) return "Unavailable"
  const total = Math.max(0, Math.round(seconds))
  const days = Math.floor(total / 86_400)
  const hours = Math.floor((total % 86_400) / 3_600)
  const minutes = Math.floor((total % 3_600) / 60)
  if (days) return `${days}d ${hours}h`
  if (hours) return `${hours}h ${minutes}m`
  if (minutes) return `${minutes}m`
  return `${total}s`
}

function relativeTime(timestamp: unknown, ageSeconds?: unknown): string {
  const explicitAge = numberValue(ageSeconds)
  const ts = numberValue(timestamp)
  const age = explicitAge ?? (ts === null ? null : Math.max(0, Date.now() / 1000 - ts))
  if (age === null) return "Unknown"
  if (age < 5) return "Now"
  if (age < 60) return `${Math.floor(age)}s ago`
  if (age < 3_600) return `${Math.floor(age / 60)}m ago`
  if (age < 86_400) return `${Math.floor(age / 3_600)}h ago`
  return `${Math.floor(age / 86_400)}d ago`
}

function versionLabel(version: Record<string, unknown> | undefined): string {
  const raw = version?.version
  return typeof raw === "string" && raw ? `v${raw.replace(/^v/, "")}` : "unknown"
}

function accessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

function authorizationHeaders(): HeadersInit {
  const token = accessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    headers: { Accept: "application/json", ...authorizationHeaders() },
    cache: "no-store",
  })
  if (response.status === 401) {
    sessionStorage.removeItem(TOKEN_KEY)
    authenticated = false
    throw new Error("Authentication required")
  }
  let payload: ApiEnvelope<T>
  try {
    payload = await response.json() as ApiEnvelope<T>
  } catch {
    throw new Error(`${path} returned ${response.status} ${response.statusText}`)
  }
  if (!response.ok || !payload.ok) throw new Error(payload.message || payload.error || `${path} failed`)
  return payload.data
}

async function apiSend<T>(path: string, method: "POST" | "PUT", body: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    method,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...authorizationHeaders() },
    body: JSON.stringify(body),
  })
  if (response.status === 401) {
    sessionStorage.removeItem(TOKEN_KEY)
    authenticated = false
    throw new Error("Authentication required")
  }
  let payload: ApiEnvelope<T>
  try {
    payload = await response.json() as ApiEnvelope<T>
  } catch {
    throw new Error(`${path} returned ${response.status} ${response.statusText}`)
  }
  if (!response.ok || !payload.ok) throw new Error(payload.message || payload.error || `${path} failed`)
  return payload.data
}

function notify(message: string, tone: NoticeTone = "info"): void {
  let region = document.querySelector<HTMLElement>("#native-toast-region")
  if (!region) {
    region = document.createElement("div")
    region.id = "native-toast-region"
    region.className = "native-toast-region"
    region.setAttribute("aria-live", "polite")
    document.body.appendChild(region)
  }
  const toast = document.createElement("div")
  toast.className = `native-toast ${tone}`
  toast.textContent = message
  region.appendChild(toast)
  window.setTimeout(() => toast.classList.add("visible"), 10)
  window.setTimeout(() => {
    toast.classList.remove("visible")
    window.setTimeout(() => toast.remove(), 180)
  }, tone === "error" ? 6_000 : 3_500)
}

function base64Url(bytes: Uint8Array): string {
  let binary = ""
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
}

function randomVerifier(): string {
  return base64Url(crypto.getRandomValues(new Uint8Array(48)))
}

async function sha256(value: string): Promise<string> {
  return base64Url(new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value))))
}

async function startOAuth(returnView: WebViewName): Promise<void> {
  loginButton.disabled = true
  loginWebButton.disabled = true
  gateDetail.textContent = "Preparing a secure OAuth authorization request…"
  try {
    const callback = `${location.origin}${UI_PATH}/callback`
    const registration = await fetch("/oauth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ client_name: "local-shell-mcp WebUI", redirect_uris: [callback] }),
    })
    if (!registration.ok) throw new Error(`Client registration failed: ${registration.status}`)
    const client = await registration.json() as { client_id: string }
    const verifier = randomVerifier()
    const state = randomVerifier()
    const challenge = await sha256(verifier)
    sessionStorage.setItem(OAUTH_PENDING_KEY, JSON.stringify({
      client_id: client.client_id,
      verifier,
      state,
      redirect_uri: callback,
      return_hash: hashForView(oauthReturnView(location.hash, returnView)),
    }))
    const authorize = new URL("/oauth/authorize", location.origin)
    authorize.searchParams.set("response_type", "code")
    authorize.searchParams.set("client_id", client.client_id)
    authorize.searchParams.set("redirect_uri", callback)
    authorize.searchParams.set("scope", "shell:read shell:write shell:execute browser:use file:share remote:use")
    authorize.searchParams.set("resource", location.origin)
    authorize.searchParams.set("code_challenge", challenge)
    authorize.searchParams.set("code_challenge_method", "S256")
    authorize.searchParams.set("state", state)
    location.assign(authorize)
  } catch (error) {
    loginButton.disabled = false
    loginWebButton.disabled = false
    gateDetail.textContent = error instanceof Error ? error.message : String(error)
  }
}

async function finishOAuthCallback(): Promise<boolean> {
  const url = new URL(location.href)
  const code = url.searchParams.get("code")
  if (!code) return false
  const pendingRaw = sessionStorage.getItem(OAUTH_PENDING_KEY)
  if (!pendingRaw) throw new Error("The OAuth request state is missing. Start authentication again.")
  const pending = JSON.parse(pendingRaw) as {
    client_id: string
    verifier: string
    state: string
    redirect_uri: string
    return_hash?: string
  }
  if (url.searchParams.get("state") !== pending.state) throw new Error("OAuth state verification failed")
  const form = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    client_id: pending.client_id,
    redirect_uri: pending.redirect_uri,
    code_verifier: pending.verifier,
  })
  const response = await fetch("/oauth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body: form,
  })
  const result = await response.json() as { access_token?: string; error_description?: string; error?: string }
  if (!response.ok || !result.access_token) throw new Error(result.error_description || result.error || "OAuth token exchange failed")
  sessionStorage.setItem(TOKEN_KEY, result.access_token)
  sessionStorage.removeItem(OAUTH_PENDING_KEY)
  callbackView = viewFromHash(pending.return_hash || "") || "overview"
  const targetUrl = callbackView === "console" ? UI_PATH : `${UI_PATH}/${hashForView(callbackView)}`
  history.replaceState({}, "", targetUrl)
  return true
}

const PAGE_TITLES: Record<Exclude<WebViewName, "console">, string> = {
  "hosted-chat": "Hosted Chat",
  overview: "Overview",
  files: "Files",
  terminals: "Terminals",
  desktop: "Desktop",
  sessions: "Sessions",
  remotes: "Remotes",
  audit: "Audit",
  workloads: "Workloads",
  activity: "Alerts and activity",
}

let nativeController: NativePageController | null = null
let nativeControllerView: WebViewName | null = null

function destroyNativeController(): void {
  unmountReactPage()
  nativeController = null
  nativeControllerView = null
}

function uiMachines(): UiMachine[] {
  return (bootstrapData?.machines?.machines || dashboardData?.machines?.machines || []) as UiMachine[]
}

function renderActiveView(): void {
  if (activeView === "console") return
  pageTitle.textContent = PAGE_TITLES[activeView]
  if (["overview", "workloads", "activity"].includes(activeView) && !dashboardData) {
    viewRoot.innerHTML = '<div class="loading-state"><span></span><strong>Loading control plane…</strong></div>'
    return
  }
  if (activeView === "overview") {
    if (nativeController) destroyNativeController()
    mountOverview(viewRoot, dashboardData!, view => showView(view as WebViewName))
    return
  }
  if (activeView === "workloads" || activeView === "activity") {
    if (nativeController) destroyNativeController()
    mountDataPage(viewRoot, activeView, dashboardData!, view => showView(view as WebViewName))
    return
  }
  if (!isNativeView(activeView)) return
  if (nativeController && nativeControllerView === activeView) return
  destroyNativeController()
  viewRoot.innerHTML = ""
  nativeController = createNativePage(activeView, {
    api: { get: apiGet, send: apiSend },
    uiPath: UI_PATH,
    liveWorkspaceEnabled: bootstrapData?.features?.live_workspace === true,
    apiPrefix: API_PREFIX,
    accessToken,
    machines: uiMachines,
    notify,
    refreshChrome: async () => {
      await refreshAll(false)
    },
  })
  nativeControllerView = activeView
  mountControllerPage(viewRoot, nativeController)
}

function showView(
  view: WebViewName,
  { syncHash = true, replaceHash = false }: { syncHash?: boolean; replaceHash?: boolean } = {},
): void {
  activeView = view
  document.body.classList.toggle("native-view-active", view !== "console" && isNativeView(view))
  if (interfaceModeForView(view) === "web") lastWebView = view
  document.querySelectorAll<HTMLButtonElement>(".nav-item[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view)
    if (button.dataset.view === view) button.setAttribute("aria-current", "page")
    else button.removeAttribute("aria-current")
  })
  const mode = interfaceModeForView(view)
  interfaceButtons.forEach((button) => {
    const active = button.dataset.interfaceMode === mode
    button.classList.toggle("active", active)
    button.setAttribute("aria-pressed", String(active))
  })
  if (view === "console") {
    destroyNativeController()
    webView.hidden = true
    consoleView.hidden = false
    initializeTerminal()
    window.requestAnimationFrame(sendResize)
  } else {
    consoleView.hidden = true
    webView.hidden = false
    renderActiveView()
  }
  if (syncHash) {
    const nextHash = hashForView(view)
    if (location.hash !== nextHash) {
      const url = `${location.pathname}${location.search}${nextHash}`
      if (replaceHash) history.replaceState({}, "", url)
      else history.pushState({}, "", url)
    }
  }
}

function syncChrome(data: DashboardData): void {
  const machines = data.machines?.machines || []
  const remoteMachineCount = machines.filter((machine) => machine.info?.local !== true).length
  const activeWorkloadCount = visibleWorkloadCount(data)
  machineNavCount.textContent = String(remoteMachineCount)
  workloadNavCount.textContent = String(activeWorkloadCount)
  machineNavCount.parentElement?.setAttribute("aria-label", `Remotes, ${remoteMachineCount} remote ${remoteMachineCount === 1 ? "machine" : "machines"}`)
  workloadNavCount.parentElement?.setAttribute("aria-label", `Terminals, ${activeWorkloadCount} ${activeWorkloadCount === 1 ? "workload" : "workloads"}`)
  const version = versionLabel(data.version)
  controllerVersion.textContent = version
  controllerOrigin.textContent = location.host
  controllerUptime.textContent = `Running for ${formatDuration(data.system?.uptime_s)}`
  controllerStatus.textContent = data.health === "critical" ? "Controller needs attention" : "Controller online"
  footerVersion.textContent = `local-shell-mcp ${version}`
  footerHealth.textContent = data.health === "healthy" ? "API healthy" : `Health: ${data.health}`
  const generated = numberValue(data.generated_at)
  footerChecked.textContent = generated === null ? "Checked just now" : `Checked ${new Date(generated * 1000).toLocaleString()}`
  updatedAt.textContent = generated === null ? "· updated just now" : `· updated ${relativeTime(generated)}`
}

async function refreshAll(manual = false): Promise<void> {
  if (refreshing) return
  refreshing = true
  document.body.classList.toggle("refreshing", manual)
  try {
    const [bootstrap, dashboard] = await Promise.all([
      apiGet<BootstrapData>("/bootstrap"),
      apiGet<DashboardData>("/dashboard"),
    ])
    bootstrapData = bootstrap
    document.querySelectorAll<HTMLElement>('[data-interface-mode="chat"]').forEach((entry) => {
      entry.hidden = bootstrap.features?.hosted_chat !== true
    })
    if (activeView === "hosted-chat" && bootstrap.features?.hosted_chat !== true) {
      showView("overview")
    }
    dashboardData = dashboard
    syncChrome(dashboard)
    const mountedController = nativeController && nativeControllerView === activeView
      ? nativeController
      : null
    renderActiveView()
    if (mountedController && mountedController === nativeController) {
      await mountedController.refresh()
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (message === "Authentication required") {
      stopRefreshTimer()
      authGate.hidden = false
      appShell.hidden = true
      gateDetail.textContent = "The session expired or this service requires OAuth authentication."
      loginButton.disabled = false
      loginWebButton.disabled = false
      return
    }
    if (!dashboardData && activeView !== "console") {
      viewRoot.innerHTML = `<div class="error-state"><h2>Unable to load the control plane</h2><p>${escapeHtml(message)}</p></div>`
    }
    updatedAt.textContent = "· refresh failed"
    footerHealth.textContent = "API unavailable"
  } finally {
    refreshing = false
    document.body.classList.remove("refreshing")
  }
}

function startRefreshTimer(): void {
  stopRefreshTimer()
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState !== "hidden") void refreshAll(false)
  }, 5_000)
}

function stopRefreshTimer(): void {
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
  refreshTimer = null
}

// Console / OpenTUI ---------------------------------------------------------
const terminalElement = document.querySelector<HTMLElement>("#terminal")!
const reconnectButton = document.querySelector<HTMLButtonElement>("#reconnect-button")!
const fullscreenButton = document.querySelector<HTMLButtonElement>("#fullscreen-button")!
const touchButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("#touchbar [data-key]"))
const keyboardButton = document.querySelector<HTMLButtonElement>("#keyboard-button")!
const stateElement = document.querySelector<HTMLElement>("#connection-state")!
const sizeElement = document.querySelector<HTMLElement>("#terminal-size")!
const terminalCopyButton = document.querySelector<HTMLButtonElement>("#terminal-copy-button")!

let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let terminalWrites: TerminalWriteBuffer | null = null
let socket: WebSocket | null = null
let reconnectTimer: number | null = null
let reconnectAttempt = 0
let manualDisconnect = false
let terminalInitialized = false
let fittedColumns = 0
let fittedRows = 0
const primaryCoarsePointer = window.matchMedia("(pointer: coarse)")
let touchInteractionActive = primaryCoarsePointer.matches
let touchKeyboardEnabled = false
let pointerSelectingTerminal = false
let publishedClipboardValue: string | null = null

function writeTerminalOutput(chunk: TerminalWriteChunk): void {
  terminalWrites?.write(chunk)
}

function updateTerminalOutputHold(): void {
  terminalWrites?.setHeld(pointerSelectingTerminal || Boolean(terminal?.hasSelection()))
}

function resetTerminalOutputHold(): void {
  pointerSelectingTerminal = false
  terminalWrites?.clear()
  terminalWrites?.setHeld(false)
  terminal?.clearSelection()
}

function setPublishedClipboard(value: string | null): void {
  publishedClipboardValue = value
  terminalCopyButton.hidden = value === null
  terminalCopyButton.classList.remove("copied")
  terminalCopyButton.textContent = "Copy invite command"
}

function finishTerminalPointerSelection(): void {
  if (!pointerSelectingTerminal) return
  pointerSelectingTerminal = false
  updateTerminalOutputHold()
}

function setConnection(state: "connecting" | "connected" | "error", label: string): void {
  stateElement.classList.remove("connected", "error")
  if (state !== "connecting") stateElement.classList.add(state)
  const strong = stateElement.querySelector("strong")
  if (strong) strong.textContent = label
}

function websocketProtocols(): string[] {
  const protocols = ["lsm-ui"]
  const token = accessToken()
  if (token) protocols.push(`bearer.${base64Url(encoder.encode(token))}`)
  return protocols
}

function sendResize(): void {
  if (!terminal || !fitAddon || consoleView.hidden) return
  const responsiveFontSize = window.innerWidth <= 720 ? 12 : 13
  if (terminal.options.fontSize !== responsiveFontSize) terminal.options.fontSize = responsiveFontSize
  fitAddon.fit()
  const resized = terminal.cols !== fittedColumns || terminal.rows !== fittedRows
  fittedColumns = terminal.cols
  fittedRows = terminal.rows
  sizeElement.textContent = `${terminal.cols} × ${terminal.rows}`
  if (socket?.readyState === WebSocket.OPEN) {
    if (resized) terminal.clear()
    socket.send(JSON.stringify({ type: "resize", cols: terminal.cols, rows: terminal.rows }))
  }
}

function currentTerminalCellAspect(): number | null {
  if (!terminal) return null
  const screen = terminalElement.querySelector<HTMLElement>(".xterm-screen")
  if (!screen) return null
  const bounds = screen.getBoundingClientRect()
  return measureTerminalCellAspect(bounds.width, bounds.height, terminal.cols, terminal.rows)
}

function clearReconnect(): void {
  if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
  reconnectTimer = null
}

function scheduleReconnect(): void {
  if (manualDisconnect || !authenticated) return
  clearReconnect()
  const delay = Math.min(8_000, 450 * 2 ** reconnectAttempt)
  reconnectAttempt += 1
  setConnection("connecting", `Reconnecting in ${(delay / 1000).toFixed(1)}s`)
  reconnectTimer = window.setTimeout(connectTerminal, delay)
}

function connectTerminal(): void {
  if (!terminal) return
  clearReconnect()
  manualDisconnect = false
  const previous = socket
  socket = null
  previous?.close()
  resetTerminalOutputHold()
  setPublishedClipboard(null)
  terminal.clear()
  writeTerminalOutput("\x1b[38;2;117;104;232mStarting local-shell-mcp OpenTUI…\x1b[0m\r\n")
  setConnection("connecting", "Connecting")
  sendResize()
  const scheme = location.protocol === "https:" ? "wss:" : "ws:"
  const url = new URL(`${scheme}//${location.host}${UI_PATH}/ws`)
  url.searchParams.set("cols", String(terminal.cols))
  url.searchParams.set("rows", String(terminal.rows))
  const aspect = currentTerminalCellAspect()
  if (aspect !== null) url.searchParams.set("cell_aspect", aspect.toFixed(4))
  const nextSocket = new WebSocket(url, websocketProtocols())
  socket = nextSocket
  nextSocket.binaryType = "arraybuffer"
  nextSocket.onopen = () => {
    if (socket !== nextSocket) return
    reconnectAttempt = 0
    setConnection("connected", "Connected")
    sendResize()
    if (!primaryCoarsePointer.matches) terminal?.focus()
  }
  nextSocket.onmessage = async (event) => {
    if (socket !== nextSocket || !terminal) return
    if (event.data instanceof ArrayBuffer) writeTerminalOutput(new Uint8Array(event.data))
    else if (event.data instanceof Blob) writeTerminalOutput(new Uint8Array(await event.data.arrayBuffer()))
    else writeTerminalOutput(String(event.data))
  }
  nextSocket.onerror = () => {
    if (socket === nextSocket) setConnection("error", "Connection error")
  }
  nextSocket.onclose = (event) => {
    if (socket !== nextSocket) return
    socket = null
    if (event.code === 4401) {
      sessionStorage.removeItem(TOKEN_KEY)
      authenticated = false
      setConnection("error", "Authentication required")
      authGate.hidden = false
      appShell.hidden = true
      stopRefreshTimer()
      gateDetail.textContent = "The session expired or this service requires OAuth authentication."
      loginButton.disabled = false
      loginWebButton.disabled = false
      return
    }
    if (event.code === 4410) {
      manualDisconnect = true
      setConnection("error", "Disconnected")
      writeTerminalOutput("\r\n\x1b[38;2;255;204;102mThe TUI exited. Use Reconnect to start a new session.\x1b[0m\r\n")
      return
    }
    if ([1011, 4400, 4408, 4429].includes(event.code)) {
      manualDisconnect = true
      setConnection("error", "Disconnected")
      writeTerminalOutput(`\r\n\x1b[38;2;255;123;139m${event.reason || "The OpenTUI session could not continue."}\x1b[0m\r\n`)
      return
    }
    if (!manualDisconnect) scheduleReconnect()
  }
}

function usesTouchKeyboard(): boolean {
  return touchInteractionActive
}

function setTouchKeyboard(enabled: boolean): void {
  if (!terminal) return
  touchKeyboardEnabled = usesTouchKeyboard() && enabled
  keyboardButton.setAttribute("aria-pressed", String(touchKeyboardEnabled))
  keyboardButton.setAttribute("aria-label", touchKeyboardEnabled ? "Hide keyboard" : "Show keyboard")
  keyboardButton.title = touchKeyboardEnabled ? "Hide keyboard" : "Show keyboard"
  const textarea = terminal.textarea
  if (!textarea) return
  textarea.readOnly = usesTouchKeyboard() && !touchKeyboardEnabled
  textarea.inputMode = touchKeyboardEnabled || !usesTouchKeyboard() ? "text" : "none"
  if (touchKeyboardEnabled) terminal.focus()
  else textarea.blur()
}

function updatePointerMode(event: PointerEvent): void {
  if (event.pointerType === "touch") {
    const wasTouchInteraction = touchInteractionActive
    touchInteractionActive = true
    if (
      event.currentTarget === terminalElement ||
      (!wasTouchInteraction && event.currentTarget !== keyboardButton)
    ) {
      setTouchKeyboard(false)
    }
  } else if (event.pointerType === "mouse") {
    touchInteractionActive = false
    setTouchKeyboard(false)
  }
}

function initializeTerminal(): void {
  if (terminalInitialized) {
    if (!socket || socket.readyState === WebSocket.CLOSED) connectTerminal()
    return
  }
  terminalInitialized = true
  terminal = new Terminal({
    allowProposedApi: false,
    allowTransparency: false,
    convertEol: false,
    cursorBlink: true,
    cursorStyle: "bar",
    cursorWidth: 2,
    fontFamily: '"JetBrains Mono", "Cascadia Code", "SFMono-Regular", Consolas, monospace',
    fontSize: 13,
    fontWeight: "400",
    fontWeightBold: "700",
    lineHeight: 1.08,
    scrollback: 6_000,
    smoothScrollDuration: 80,
    theme: {
      background: "#111111",
      foreground: "#edf3ff",
      cursor: "#ffffff",
      cursorAccent: "#0d1422",
      selectionBackground: "#4e5e82aa",
      black: "#0d1422", red: "#f7768e", green: "#79d69f", yellow: "#e0af68", blue: "#7aa2f7",
      magenta: "#bb9af7", cyan: "#5eead4", white: "#edf3ff", brightBlack: "#68758e",
      brightRed: "#ff98aa", brightGreen: "#9be7b7", brightYellow: "#f3c97f", brightBlue: "#9bbcff",
      brightMagenta: "#d3b4ff", brightCyan: "#8af2e2", brightWhite: "#ffffff",
    },
  })
  fitAddon = new FitAddon()
  terminal.loadAddon(createImageAddon())
  terminal.loadAddon(fitAddon)
  terminal.open(terminalElement)
  terminalWrites = new TerminalWriteBuffer((chunk) => terminal?.write(chunk), {
    onOverflow: () => {
      pointerSelectingTerminal = false
      terminal?.clearSelection()
    },
  })
  terminal.parser.registerOscHandler(WEB_CLIPBOARD_OSC, (data) => {
    const payload = parseWebClipboardPayload(data)
    if (payload === null) return false
    setPublishedClipboard(payload.type === "set" ? payload.value : null)
    return true
  })
  terminal.onSelectionChange(updateTerminalOutputHold)
  terminal.onData((data) => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(encoder.encode(data))
  })
  terminal.onBinary((data) => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(Uint8Array.from(data, (character: string) => character.charCodeAt(0) & 0xff))
  })
  touchButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.key || ""
      if (key === "keyboard") {
        setTouchKeyboard(!touchKeyboardEnabled)
        return
      }
      const sequence = TERMINAL_KEY_SEQUENCES[key]
      if (sequence && socket?.readyState === WebSocket.OPEN) socket.send(encoder.encode(sequence))
      if (!usesTouchKeyboard() || touchKeyboardEnabled) terminal?.focus()
      else terminal?.textarea?.blur()
    })
  })
  terminalElement.addEventListener("pointerdown", (event) => {
    updatePointerMode(event)
    if (event.pointerType === "mouse" && event.button === 0) {
      pointerSelectingTerminal = true
      updateTerminalOutputHold()
    }
  }, { capture: true })
  touchButtons.forEach((button) => {
    button.addEventListener("pointerdown", updatePointerMode, { capture: true })
  })
  terminalElement.addEventListener("pointerup", () => {
    finishTerminalPointerSelection()
    if (!usesTouchKeyboard() || touchKeyboardEnabled) return
    window.requestAnimationFrame(() => terminal?.textarea?.blur())
  })
  window.addEventListener("pointerup", finishTerminalPointerSelection, { capture: true })
  window.addEventListener("pointercancel", finishTerminalPointerSelection, { capture: true })
  setTouchKeyboard(false)
  terminal.textarea?.addEventListener("focus", () => {
    if (!usesTouchKeyboard() || touchKeyboardEnabled) return
    terminal?.textarea?.blur()
  })
  const resizeObserver = new ResizeObserver(() => window.requestAnimationFrame(sendResize))
  resizeObserver.observe(terminalElement)
  connectTerminal()
}

async function writeClipboardText(value: string): Promise<boolean> {
  const textarea = document.createElement("textarea")
  textarea.value = value
  textarea.style.position = "fixed"
  textarea.style.opacity = "0"
  document.body.appendChild(textarea)
  try {
    try {
      textarea.select()
      if (document.execCommand("copy")) return true
    } catch {
      // Try the asynchronous Clipboard API below.
    }
    await navigator.clipboard.writeText(value)
    return true
  } catch {
    return false
  } finally {
    textarea.remove()
    terminal?.focus()
  }
}

async function copyTerminalSelection(): Promise<void> {
  const selection = terminal?.getSelection()
  if (!selection) return
  if (await writeClipboardText(selection)) terminal?.clearSelection()
}

async function copyPublishedClipboard(): Promise<void> {
  if (publishedClipboardValue === null) return
  const copied = await writeClipboardText(publishedClipboardValue)
  terminalCopyButton.textContent = copied ? "Copied" : "Copy failed"
  terminalCopyButton.classList.toggle("copied", copied)
}

window.addEventListener("keydown", (event) => {
  if (activeView !== "console" || !terminal || document.body.classList.contains("navigation-open")) return
  const selectionShortcut = browserSelectionShortcut(event)
  if (selectionShortcut) {
    event.preventDefault()
    event.stopImmediatePropagation()
    if (selectionShortcut === "select-all") terminal.selectAll()
    else void copyTerminalSelection()
    return
  }
  if (
    publishedClipboardValue !== null &&
    event.key.toLowerCase() === "c" &&
    !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey
  ) {
    event.preventDefault()
    event.stopImmediatePropagation()
    void copyPublishedClipboard()
    return
  }
  const sequence = browserShortcutSequence(event)
  if (!sequence || socket?.readyState !== WebSocket.OPEN) return
  event.preventDefault()
  event.stopImmediatePropagation()
  socket.send(encoder.encode(sequence))
}, { capture: true })

reconnectButton.addEventListener("click", () => {
  reconnectAttempt = 0
  connectTerminal()
})
terminalCopyButton.addEventListener("click", () => void copyPublishedClipboard())
fullscreenButton.addEventListener("click", () => {
  if (document.fullscreenElement) void document.exitFullscreen()
  else void consoleView.requestFullscreen()
})
document.addEventListener("fullscreenchange", () => {
  fullscreenButton.textContent = document.fullscreenElement ? "Exit fullscreen" : "Fullscreen"
  window.requestAnimationFrame(sendResize)
  try {
    if (document.fullscreenElement) void navigator.keyboard?.lock?.(["Escape"])?.catch(() => undefined)
    else navigator.keyboard?.unlock?.()
  } catch {
    // Keyboard lock is optional.
  }
})
primaryCoarsePointer.addEventListener("change", (event) => {
  touchInteractionActive = event.matches
  setTouchKeyboard(false)
})
window.addEventListener("resize", () => window.requestAnimationFrame(sendResize))
window.addEventListener("beforeunload", () => {
  stopRefreshTimer()
  manualDisconnect = true
  clearReconnect()
  socket?.close()
})

// App wiring ---------------------------------------------------------------
document.querySelectorAll<HTMLButtonElement>(".nav-item[data-view]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view as WebViewName))
})
interfaceButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const mode = button.dataset.interfaceMode
    showView(mode === "tui" ? "console" : mode === "chat" ? "hosted-chat" : lastWebView)
  })
})
loginButton.addEventListener("click", () => void startOAuth("console"))
loginWebButton.addEventListener("click", () => void startOAuth("overview"))
refreshButton.addEventListener("click", () => void refreshAll(true))
openConsoleButton.addEventListener("click", () => showView("console"))
document.addEventListener("visibilitychange", () => {
  if (authenticated && document.visibilityState === "visible") void refreshAll(false)
})
window.addEventListener("popstate", () => {
  showView(viewFromHash(location.hash) || "overview", { syncHash: false })
})

async function boot(): Promise<void> {
  try {
    await finishOAuthCallback()
    bootstrapData = await apiGet<BootstrapData>("/bootstrap")
    authenticated = true
    authGate.hidden = true
    appShell.hidden = false
    const initialView = callbackView || viewFromHash(location.hash) || "overview"
    showView(initialView, { syncHash: callbackView !== "console", replaceHash: true })
    await refreshAll(false)
    startRefreshTimer()
  } catch (error) {
    authenticated = false
    appShell.hidden = true
    authGate.hidden = false
    loginButton.disabled = false
    loginWebButton.disabled = false
    gateDetail.textContent = error instanceof Error ? error.message : String(error)
  }
}

void boot()
