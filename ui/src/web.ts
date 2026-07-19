import "./liquid-glass"
import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import { createImageAddon } from "./image-support"
import { browserShortcutSequence } from "./keyboard"
import { measureTerminalCellAspect } from "./terminal-geometry"

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

const UI_PATH = (window.__LSM_UI_CONFIG__?.uiPath || "/ui").replace(/\/$/, "")
const API_PREFIX = (window.__LSM_UI_CONFIG__?.apiPrefix || "/api/ui").replace(/\/$/, "")
const terminalElement = document.querySelector<HTMLElement>("#terminal")!
const authGate = document.querySelector<HTMLElement>("#auth-gate")!
const loginButton = document.querySelector<HTMLButtonElement>("#login-button")!
const reconnectButton = document.querySelector<HTMLButtonElement>("#reconnect-button")!
const fullscreenButton = document.querySelector<HTMLButtonElement>("#fullscreen-button")!
const touchButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("#touchbar [data-key]"))
const keyboardButton = document.querySelector<HTMLButtonElement>("#keyboard-button")!
const stateElement = document.querySelector<HTMLElement>("#connection-state")!
const sizeElement = document.querySelector<HTMLElement>("#terminal-size")!
const gateDetail = document.querySelector<HTMLElement>("#gate-detail")!
const wallpaper = document.querySelector<HTMLElement>(".wallpaper")!
wallpaper.style.backgroundImage =
  `linear-gradient(145deg, rgba(2, 7, 17, 0.24), rgba(2, 7, 17, 0.78)), url("${UI_PATH}/wallpaper")`

const TOKEN_KEY = "lsm.ui.access_token"
const OAUTH_PENDING_KEY = "lsm.ui.oauth_pending"
const encoder = new TextEncoder()

const terminal = new Terminal({
  allowProposedApi: false,
  convertEol: false,
  cursorBlink: true,
  cursorStyle: "bar",
  cursorWidth: 2,
  fontFamily: '"JetBrains Mono", "Cascadia Code", "SFMono-Regular", Consolas, monospace',
  fontSize: 13,
  fontWeight: "400",
  fontWeightBold: "700",
  letterSpacing: 0,
  lineHeight: 1.08,
  scrollback: 6_000,
  smoothScrollDuration: 80,
  theme: {
    background: "#080b14",
    foreground: "#edf3ff",
    cursor: "#5eead4",
    cursorAccent: "#080b14",
    selectionBackground: "#334b65aa",
    black: "#080b14",
    red: "#f7768e",
    green: "#79d69f",
    yellow: "#e0af68",
    blue: "#7aa2f7",
    magenta: "#bb9af7",
    cyan: "#5eead4",
    white: "#edf3ff",
    brightBlack: "#68758e",
    brightRed: "#ff98aa",
    brightGreen: "#9be7b7",
    brightYellow: "#f3c97f",
    brightBlue: "#9bbcff",
    brightMagenta: "#d3b4ff",
    brightCyan: "#8af2e2",
    brightWhite: "#ffffff",
  },
})
const fitAddon = new FitAddon()
terminal.loadAddon(createImageAddon())
terminal.loadAddon(fitAddon)
terminal.open(terminalElement)

let fittedColumns = terminal.cols
let fittedRows = terminal.rows
const primaryCoarsePointer = window.matchMedia("(pointer: coarse)")
let touchInteractionActive = primaryCoarsePointer.matches
let touchKeyboardEnabled = false

function usesTouchKeyboard(): boolean {
  return touchInteractionActive
}

function setTouchKeyboard(enabled: boolean): void {
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

setTouchKeyboard(false)
terminal.textarea?.addEventListener("focus", () => {
  if (!usesTouchKeyboard() || touchKeyboardEnabled) return
  terminal.textarea?.blur()
})

let socket: WebSocket | null = null
let reconnectTimer: number | null = null
let manualDisconnect = false
let reconnectAttempt = 0
let authenticated = false

const touchSequences: Record<string, string> = {
  escape: "\u001b",
  tab: "\t",
  left: "\u001b[D",
  up: "\u001b[A",
  down: "\u001b[B",
  right: "\u001b[C",
  enter: "\r",
  help: "\u001bOP",
}

function sendTerminalInput(sequence: string): void {
  if (socket?.readyState !== WebSocket.OPEN) return
  socket.send(encoder.encode(sequence))
}
window.addEventListener(
  "keydown",
  (event) => {
    const sequence = browserShortcutSequence(event)
    if (!sequence || socket?.readyState !== WebSocket.OPEN) return
    event.preventDefault()
    event.stopImmediatePropagation()
    sendTerminalInput(sequence)
  },
  { capture: true },
)

function setConnection(state: "connecting" | "connected" | "error", label: string): void {
  stateElement.classList.remove("connected", "error")
  if (state !== "connecting") stateElement.classList.add(state)
  const strong = stateElement.querySelector("strong")
  if (strong) strong.textContent = label
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

function accessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

function authorizationHeaders(): HeadersInit {
  const token = accessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function checkAccess(): Promise<boolean> {
  const response = await fetch(`${API_PREFIX}/bootstrap`, {
    headers: { Accept: "application/json", ...authorizationHeaders() },
    cache: "no-store",
  })
  if (response.ok) return true
  if (response.status === 401) return false
  throw new Error(`UI bootstrap failed: ${response.status} ${response.statusText}`)
}

async function startOAuth(): Promise<void> {
  loginButton.disabled = true
  gateDetail.textContent = "Preparing a secure OAuth authorization request…"
  try {
    const callback = `${location.origin}${UI_PATH}/callback`
    const registration = await fetch("/oauth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        client_name: "local-shell-mcp WebUI",
        redirect_uris: [callback],
      }),
    })
    if (!registration.ok) throw new Error(`Client registration failed: ${registration.status}`)
    const client = (await registration.json()) as { client_id: string }
    const verifier = randomVerifier()
    const state = randomVerifier()
    const challenge = await sha256(verifier)
    sessionStorage.setItem(
      OAUTH_PENDING_KEY,
      JSON.stringify({ client_id: client.client_id, verifier, state, redirect_uri: callback }),
    )
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
  const result = (await response.json()) as { access_token?: string; error_description?: string; error?: string }
  if (!response.ok || !result.access_token) {
    throw new Error(result.error_description || result.error || "OAuth token exchange failed")
  }
  sessionStorage.setItem(TOKEN_KEY, result.access_token)
  sessionStorage.removeItem(OAUTH_PENDING_KEY)
  history.replaceState({}, "", UI_PATH)
  return true
}

function websocketProtocols(): string[] {
  const protocols = ["lsm-ui"]
  const token = accessToken()
  if (token) protocols.push(`bearer.${base64Url(encoder.encode(token))}`)
  return protocols
}

function sendResize(): void {
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
  const screen = terminalElement.querySelector<HTMLElement>(".xterm-screen")
  if (!screen) return null
  const bounds = screen.getBoundingClientRect()
  return measureTerminalCellAspect(bounds.width, bounds.height, terminal.cols, terminal.rows)
}

function clearReconnect(): void {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function scheduleReconnect(): void {
  if (manualDisconnect || !authenticated) return
  clearReconnect()
  const delay = Math.min(8_000, 450 * 2 ** reconnectAttempt)
  reconnectAttempt += 1
  setConnection("connecting", `Reconnecting in ${(delay / 1000).toFixed(1)}s`)
  reconnectTimer = window.setTimeout(() => connect(), delay)
}

function connect(): void {
  clearReconnect()
  manualDisconnect = false
  const previous = socket
  socket = null
  previous?.close()
  terminal.clear()
  terminal.write("\x1b[38;2;87;215;255mStarting local-shell-mcp OpenTUI…\x1b[0m\r\n")
  setConnection("connecting", "Connecting")
  sendResize()
  const scheme = location.protocol === "https:" ? "wss:" : "ws:"
  const url = new URL(`${scheme}//${location.host}${UI_PATH}/ws`)
  url.searchParams.set("cols", String(terminal.cols))
  url.searchParams.set("rows", String(terminal.rows))
  const cellAspect = currentTerminalCellAspect()
  if (cellAspect !== null) url.searchParams.set("cell_aspect", cellAspect.toFixed(4))
  const nextSocket = new WebSocket(url, websocketProtocols())
  socket = nextSocket
  nextSocket.binaryType = "arraybuffer"
  nextSocket.onopen = () => {
    if (socket !== nextSocket) return
    reconnectAttempt = 0
    setConnection("connected", "Connected")
    authGate.hidden = true
    sendResize()
    if (usesTouchKeyboard()) setTouchKeyboard(false)
    else terminal.focus()
  }
  nextSocket.onmessage = async (event) => {
    if (socket !== nextSocket) return
    if (event.data instanceof ArrayBuffer) terminal.write(new Uint8Array(event.data))
    else if (event.data instanceof Blob) terminal.write(new Uint8Array(await event.data.arrayBuffer()))
    else terminal.write(String(event.data))
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
      authGate.hidden = false
      setConnection("error", "Authentication required")
      gateDetail.textContent = "The session expired or this service requires OAuth authentication."
      loginButton.disabled = false
      return
    }
    if (event.code === 4410) {
      manualDisconnect = true
      setConnection("error", "Disconnected")
      terminal.write("\r\n\x1b[38;2;255;204;102mThe TUI exited. Use Reconnect to start a new session.\x1b[0m\r\n")
      return
    }
    if ([1011, 4400, 4408, 4429].includes(event.code)) {
      manualDisconnect = true
      const detail = event.reason ||
        (event.code === 4408
          ? "The terminal session reached its idle timeout."
          : event.code === 4429
            ? "The server has reached its human-interface session limit."
            : "The OpenTUI process could not be started.")
      setConnection("error", "Disconnected")
      terminal.write(`\r\n\x1b[38;2;255;123;139m${detail}\x1b[0m\r\nUse Reconnect after correcting the problem.\r\n`)
      return
    }
    if (!manualDisconnect) scheduleReconnect()
  }
}

terminal.onData((data) => {
  if (socket?.readyState === WebSocket.OPEN) socket.send(encoder.encode(data))
})
terminal.onBinary((data) => {
  if (socket?.readyState !== WebSocket.OPEN) return
  socket.send(Uint8Array.from(data, (character) => character.charCodeAt(0) & 0xff))
})

touchButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.dataset.key || ""
    if (key === "keyboard") {
      setTouchKeyboard(!touchKeyboardEnabled)
      return
    }
    const sequence = touchSequences[key]
    if (sequence) sendTerminalInput(sequence)
    if (!usesTouchKeyboard() || touchKeyboardEnabled) terminal.focus()
    else terminal.textarea?.blur()
  })
})

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

terminalElement.addEventListener("pointerdown", updatePointerMode, { capture: true })
touchButtons.forEach((button) => {
  button.addEventListener("pointerdown", updatePointerMode, { capture: true })
})

terminalElement.addEventListener("pointerup", () => {
  if (!usesTouchKeyboard() || touchKeyboardEnabled) return
  window.requestAnimationFrame(() => terminal.textarea?.blur())
})

primaryCoarsePointer.addEventListener("change", (event) => {
  touchInteractionActive = event.matches
  setTouchKeyboard(false)
})

const resizeObserver = new ResizeObserver(() => window.requestAnimationFrame(sendResize))
resizeObserver.observe(terminalElement)
window.addEventListener("resize", () => window.requestAnimationFrame(sendResize))
window.addEventListener("beforeunload", () => {
  manualDisconnect = true
  clearReconnect()
  socket?.close()
})

loginButton.addEventListener("click", () => void startOAuth())
reconnectButton.addEventListener("click", () => {
  reconnectAttempt = 0
  connect()
})
fullscreenButton.addEventListener("click", () => {
  if (document.fullscreenElement) void document.exitFullscreen()
  else void document.documentElement.requestFullscreen()
})

function syncFullscreenKeyboardLock(): void {
  try {
    if (document.fullscreenElement) {
      void navigator.keyboard?.lock?.(["Escape"])?.catch(() => undefined)
    } else {
      navigator.keyboard?.unlock?.()
    }
  } catch {
    // Unsupported or denied keyboard locks fall back to Ctrl+[ for Escape.
  }
}

document.addEventListener("fullscreenchange", () => {
  const label = document.fullscreenElement ? "Exit fullscreen" : "Fullscreen"
  fullscreenButton.title = label
  fullscreenButton.setAttribute("aria-label", label)
  const wideLabel = fullscreenButton.querySelector<HTMLElement>(".wide-label")
  if (wideLabel) wideLabel.textContent = label
  terminal.focus()
  window.requestAnimationFrame(sendResize)
  syncFullscreenKeyboardLock()
})

async function boot(): Promise<void> {
  try {
    await finishOAuthCallback()
    authenticated = await checkAccess()
    if (!authenticated) {
      authGate.hidden = false
      setConnection("error", "Authentication required")
      loginButton.disabled = false
      return
    }
    authGate.hidden = true
    connect()
  } catch (error) {
    authenticated = false
    authGate.hidden = false
    setConnection("error", "Unable to start")
    gateDetail.textContent = error instanceof Error ? error.message : String(error)
    loginButton.disabled = false
  }
}

void boot()
