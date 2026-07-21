import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import { createImageAddon } from "./image-support"
import { browserSelectionShortcut, browserShortcutSequence } from "./keyboard"
import { measureTerminalCellAspect } from "./terminal-geometry"
import { hashForView, interfaceModeForView, viewFromHash, type WebViewName } from "./web-mode"

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
type Todo = Record<string, unknown>

type BootstrapData = {
  version?: Record<string, unknown>
  machines?: { machines?: Machine[]; counts?: Record<string, number> }
  todos?: { revision?: number; todos?: Todo[] }
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
  todo_counts?: { total?: number; open?: number }
}

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
const pageName = document.querySelector<HTMLElement>("#page-name")!
const pageTitle = document.querySelector<HTMLElement>("#page-title")!
const pageDescription = document.querySelector<HTMLElement>("#page-description")!
const refreshButton = document.querySelector<HTMLButtonElement>("#refresh-button")!
const openConsoleButton = document.querySelector<HTMLButtonElement>("#open-console-button")!
const interfaceButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-interface-mode]"))
const updatedAt = document.querySelector<HTMLElement>("#updated-at")!
const machineNavCount = document.querySelector<HTMLElement>("#machine-nav-count")!
const workloadNavCount = document.querySelector<HTMLElement>("#workload-nav-count")!
const todoNavCount = document.querySelector<HTMLElement>("#todo-nav-count")!
const controllerStatus = document.querySelector<HTMLElement>("#controller-status")!
const controllerUptime = document.querySelector<HTMLElement>("#controller-uptime")!
const controllerVersion = document.querySelector<HTMLElement>("#controller-version")!
const controllerOrigin = document.querySelector<HTMLElement>("#controller-origin")!
const footerVersion = document.querySelector<HTMLElement>("#footer-version")!
const footerHealth = document.querySelector<HTMLElement>("#footer-health")!
const footerChecked = document.querySelector<HTMLElement>("#footer-checked")!

let activeView: WebViewName = "overview"
let lastWebView: Exclude<WebViewName, "console"> = "overview"
let authenticated = false
let bootstrapData: BootstrapData | null = null
let dashboardData: DashboardData | null = null
let refreshTimer: number | null = null
let callbackView: WebViewName | null = null
let refreshing = false

const metricHistory = {
  cpu: [] as number[],
  memory: [] as number[],
  disk: [] as number[],
}

const ICONS = {
  check: '<svg viewBox="0 0 24 24"><path d="m7 12 3 3 7-7"/></svg>',
  warning: '<svg viewBox="0 0 24 24"><path d="M12 4 3 20h18zM12 9v5M12 17h.01"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  cpu: '<svg viewBox="0 0 24 24"><path d="M8 2v3M16 2v3M8 19v3M16 19v3M2 8h3M2 16h3M19 8h3M19 16h3"/><rect x="6" y="6" width="12" height="12" rx="3"/><path d="M9 9h6v6H9z"/></svg>',
  memory: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>',
  disk: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.66 3.13 3 7 3s7-1.34 7-3V6M5 12v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6"/></svg>',
  network: '<svg viewBox="0 0 24 24"><path d="M12 20V10M7 15l5 5 5-5M4 4h16"/></svg>',
  machine: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 21h8M12 18v3"/></svg>',
  gpu: '<svg viewBox="0 0 24 24"><path d="M4 7h16v10H4zM8 4v3M16 4v3M8 17v3M16 17v3"/><circle cx="9" cy="12" r="2"/><path d="M14 10h3M14 14h3"/></svg>',
  session: '<svg viewBox="0 0 24 24"><path d="m7 8 4 4-4 4M13 16h4"/></svg>',
}

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

function formatBytes(value: unknown): string {
  const bytes = numberValue(value)
  if (bytes === null) return "Unavailable"
  const units = ["B", "KB", "MB", "GB", "TB"]
  let amount = Math.max(0, bytes)
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024
    unit += 1
  }
  const digits = amount >= 100 || unit === 0 ? 0 : amount >= 10 ? 1 : 2
  return `${amount.toFixed(digits)} ${units[unit]}`
}

function formatRate(value: unknown): string {
  const bytes = numberValue(value)
  if (bytes === null) return "—"
  const formatted = formatBytes(bytes)
  return formatted === "Unavailable" ? "—" : `${formatted}/s`
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

function valueOrDash(value: unknown, suffix = ""): string {
  const number = numberValue(value)
  return number === null ? "—" : `${Math.round(number)}${suffix}`
}

function seededSeries(value: number, phase: number): number[] {
  return Array.from({ length: 11 }, (_, index) => {
    const wave = Math.sin((index + phase) * 1.07) * Math.max(2.5, value * 0.075)
    const drift = (index - 5) * Math.max(.08, value * .002)
    return Math.max(0, Math.min(100, value + wave + drift))
  })
}

function pushMetric(history: number[], value: unknown, phase: number): void {
  const numeric = numberValue(value)
  if (numeric === null) return
  if (!history.length) history.push(...seededSeries(numeric, phase))
  else history.push(numeric)
  if (history.length > 20) history.splice(0, history.length - 20)
}

function sparkline(values: number[], className: string): string {
  const samples = values.length > 1 ? values : [0, 0]
  const width = 220
  const height = 52
  const min = Math.min(...samples)
  const max = Math.max(...samples)
  const range = Math.max(1, max - min)
  const points = samples.map((value, index) => {
    const x = index * width / Math.max(1, samples.length - 1)
    const y = 42 - ((value - min) / range) * 27
    return [x, y]
  })
  const line = points.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ")
  const area = `${line} L${width} 48 L0 48 Z`
  return `<div class="sparkline ${className}"><svg preserveAspectRatio="none" viewBox="0 0 220 52"><path class="area" d="${area}"/><path class="line" d="${line}"/></svg></div>`
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
      return_hash: location.hash || hashForView(returnView),
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

function healthPresentation(health: Health, alerts: Alert[]): { eyebrow: string; title: string; detail: string; icon: string } {
  if (health === "critical") {
    return {
      eyebrow: "CRITICAL HEALTH",
      title: "Critical issue detected",
      detail: alerts[0]?.detail || "A controller or worker condition requires immediate attention.",
      icon: ICONS.warning,
    }
  }
  if (health === "attention") {
    return {
      eyebrow: "ATTENTION NEEDED",
      title: "Some items need attention",
      detail: alerts[0]?.detail || "The control plane is available, but one or more non-critical items should be reviewed.",
      icon: ICONS.warning,
    }
  }
  return {
    eyebrow: "SYSTEM HEALTH",
    title: "All systems operational",
    detail: "The controller and connected workers are healthy. No critical alerts require your attention.",
    icon: ICONS.check,
  }
}

function machinePlatform(machine: Machine): string {
  const info = machine.info || {}
  return stringValue(info.platform) || stringValue(info.system) || (info.local ? "Local controller" : "Remote worker")
}

function machineIcon(machine: Machine): string {
  const capabilities = machine.capabilities || []
  return capabilities.some((item) => item.toLowerCase().includes("gpu")) ? ICONS.gpu : ICONS.machine
}

function machineRows(machines: Machine[], localCpu?: unknown): string {
  if (!machines.length) return '<tr><td colspan="6"><div class="empty-state">No machines are registered.</div></td></tr>'
  return machines.map((machine, index) => {
    const info = machine.info || {}
    const status = stringValue(machine.status, "unknown")
    const online = status === "online"
    const cpu = index === 0 ? numberValue(localCpu) : numberValue(info.cpu_percent)
    const capabilities = (machine.capabilities || []).slice(0, 4)
    const version = stringValue(info.version) || stringValue(info.lsm_version)
    const subtitle = [machinePlatform(machine), version ? `LSM ${version}` : ""].filter(Boolean).join(" · ")
    return `<tr>
      <td><div class="machine-cell"><span class="machine-avatar ${index === 0 ? "local" : index % 2 ? "gpu" : "lab"}">${machineIcon(machine)}</span><span><strong>${escapeHtml(machine.name || "unnamed")}</strong><small>${escapeHtml(subtitle)}</small></span></div></td>
      <td><span class="status-chip ${online ? "online" : "offline"}"><i></i>${escapeHtml(status)}</span></td>
      <td>${cpu === null ? '<span class="last-seen">Not reported</span>' : `<div class="resource-mini"><span><i style="width:${Math.max(0, Math.min(100, cpu))}%"></i></span><small>CPU ${Math.round(cpu)}%</small></div>`}</td>
      <td><div class="tag-row">${capabilities.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("") || '<span class="last-seen">None reported</span>'}</div></td>
      <td><span class="last-seen ${online ? "now" : ""}">${relativeTime(machine.last_seen, machine.last_seen_age_s)}</span></td>
      <td><button class="row-menu" type="button" aria-label="More actions">•••</button></td>
    </tr>`
  }).join("")
}

function machineTable(data: DashboardData, full = false): string {
  const machines = data.machines?.machines || []
  return `<div class="table-wrap"><table class="${full ? "large-table" : ""}">
    <thead><tr><th>Machine</th><th>Status</th><th>Resources</th><th>Capabilities</th><th>Last seen</th><th></th></tr></thead>
    <tbody>${machineRows(machines, data.system?.cpu_percent)}</tbody>
  </table></div>`
}

function workloadIdentity(item: Job | Session, kind: "job" | "session"): { name: string; detail: string; node: string; status: string; elapsed: string } {
  const name = stringValue(item.name) || stringValue(item.job_id) || stringValue(item.session_id) || (kind === "job" ? "Tracked job" : "Shell session")
  const detail = stringValue(item.command) || stringValue(item.cwd) || stringValue(item.workdir) || stringValue(item.path) || "No command detail"
  const node = stringValue(item.machine) || stringValue(item.node) || "local"
  const status = stringValue(item.status, kind === "job" ? "running" : "attached")
  const created = numberValue(item.created_at) || numberValue(item.started_at)
  const elapsedSeconds = numberValue(item.elapsed_s) ?? (created === null ? null : Date.now() / 1000 - created)
  return { name, detail, node, status, elapsed: formatDuration(elapsedSeconds) }
}

function workloadRows(data: DashboardData, limit = 3): string {
  const rows = [
    ...(data.jobs || []).map((item) => ({ item, kind: "job" as const })),
    ...(data.sessions || []).map((item) => ({ item, kind: "session" as const })),
  ].slice(0, limit)
  if (!rows.length) return '<div class="empty-state">No active jobs or persistent sessions.</div>'
  return rows.map(({ item, kind }) => {
    const workload = workloadIdentity(item, kind)
    return `<div class="workload-row">
      <div class="workload-icon ${kind === "job" ? "running" : "session"}">${kind === "job" ? "<span></span>" : ICONS.session}</div>
      <div class="workload-main"><div><strong>${escapeHtml(workload.name)}</strong><span class="type-label ${kind === "session" ? "session-label" : ""}">${kind}</span></div><code>${escapeHtml(workload.detail)}</code></div>
      <div class="workload-node"><span class="tiny-avatar">${escapeHtml(workload.node.slice(0, 1).toUpperCase())}</span>${escapeHtml(workload.node)}</div>
      <div class="workload-time"><strong>${escapeHtml(workload.elapsed)}</strong><small>${escapeHtml(workload.status)}</small></div>
      <button class="row-action" type="button" data-view="console">Open</button>
    </div>`
  }).join("")
}

function activityRows(entries: Activity[], limit = 4): string {
  const rows = entries.slice(0, limit)
  if (!rows.length) return '<div class="empty-state">No recent MCP activity.</div>'
  return rows.map((entry) => {
    const kind = stringValue(entry.kind, "success")
    const running = kind === "running"
    const failed = kind === "failed"
    return `<div class="activity-item">
      <div class="activity-state ${failed ? "failed" : running ? "running" : "success"}">${running ? "<span></span>" : failed ? ICONS.warning : ICONS.check}</div>
      <div><strong>${escapeHtml(entry.title || "MCP activity")}</strong><p>${failed ? "Failed" : running ? "Running" : "Completed"} on <b>${escapeHtml(entry.node || "local")}</b></p><small>${relativeTime(entry.timestamp)}</small></div>
      <span class="duration ${running ? "live" : ""}">${running ? "LIVE" : failed ? "FAILED" : "OK"}</span>
    </div>`
  }).join("")
}

function alertItems(alerts: Alert[], limit = 2): string {
  const rows = alerts.slice(0, limit)
  if (!rows.length) return '<div class="empty-state">Nothing needs attention.</div>'
  return rows.map((alert) => {
    const severity = stringValue(alert.severity, "info")
    return `<div class="attention-item ${severity === "warning" || severity === "critical" ? "warning-item" : "info-item"}">
      <div class="attention-icon">${severity === "warning" || severity === "critical" ? ICONS.warning : ICONS.info}</div>
      <div><strong>${escapeHtml(alert.title || "Notice")}</strong><p>${escapeHtml(alert.detail || "No additional detail")}</p><small>${relativeTime(undefined, alert.age_s)}</small></div>
    </div>`
  }).join("")
}

function metricCard(options: {
  icon: string
  tone: string
  label: string
  value: unknown
  suffix?: string
  detailLeft: string
  detailRight: string
  history: number[]
  lineClass: string
}): string {
  const numeric = numberValue(options.value)
  return `<article class="metric-card">
    <div class="metric-head"><div class="metric-icon ${options.tone}">${options.icon}</div><span class="trend neutral">Live</span></div>
    <div class="metric-label">${escapeHtml(options.label)}</div>
    <div class="metric-value ${numeric === null ? "unavailable" : ""}">${numeric === null ? "Unavailable" : `${Math.round(numeric)}<span>${escapeHtml(options.suffix || "")}</span>`}</div>
    ${sparkline(options.history, options.lineClass)}
    <div class="metric-foot"><span>${escapeHtml(options.detailLeft)}</span><span>${escapeHtml(options.detailRight)}</span></div>
  </article>`
}

function overviewTemplate(data: DashboardData): string {
  const health = data.health || "healthy"
  const alerts = data.alerts || []
  const presentation = healthPresentation(health, alerts)
  const system = data.system || {}
  const machines = data.machines?.machines || []
  const totalMachines = data.machines?.counts?.total ?? machines.length
  const activeJobs = data.jobs?.length || 0
  const sessions = data.session_count ?? data.sessions?.length ?? 0
  const openTodos = data.todo_counts?.open || 0
  const version = versionLabel(data.version)
  pushMetric(metricHistory.cpu, system.cpu_percent, 0)
  pushMetric(metricHistory.memory, system.memory_percent, 3)
  pushMetric(metricHistory.disk, system.disk_percent, 6)

  return `<section class="status-banner ${health}">
    <div class="status-illustration"><div class="pulse-ring outer"></div><div class="pulse-ring inner"></div><div class="check-circle">${presentation.icon}</div></div>
    <div class="status-copy"><div class="eyebrow"><span class="status-dot"></span>${presentation.eyebrow}</div><h2>${escapeHtml(presentation.title)}</h2><p>${escapeHtml(presentation.detail)}</p></div>
    <div class="status-stats"><div><strong>${totalMachines}</strong><span>Machines</span></div><div><strong>${activeJobs}</strong><span>Active jobs</span></div><div><strong>${sessions}</strong><span>Sessions</span></div><div><strong>${data.audit_total_24h || 0}</strong><span>MCP calls · 24h</span></div></div>
  </section>
  <section class="metric-grid">
    ${metricCard({ icon: ICONS.cpu, tone: "violet", label: "CPU usage", value: system.cpu_percent, suffix: "%", detailLeft: `${system.cpu_count || "—"} cores`, detailRight: `Load ${system.load_1m ?? "—"}`, history: metricHistory.cpu, lineClass: "violet-line" })}
    ${metricCard({ icon: ICONS.memory, tone: "blue", label: "Memory usage", value: system.memory_percent, suffix: "%", detailLeft: `${formatBytes(system.memory_used_bytes)} used`, detailRight: `${formatBytes(system.memory_total_bytes)} total`, history: metricHistory.memory, lineClass: "blue-line" })}
    ${metricCard({ icon: ICONS.disk, tone: "amber", label: "Workspace disk", value: system.disk_percent, suffix: "%", detailLeft: `${formatBytes(system.disk_used_bytes)} used`, detailRight: `${formatBytes(system.disk_total_bytes)} total`, history: metricHistory.disk, lineClass: "amber-line" })}
    <article class="metric-card network-card"><div class="metric-head"><div class="metric-icon green">${ICONS.network}</div><span class="trend positive">Live</span></div><div class="metric-label">Network throughput</div><div class="network-values"><div><span class="download-arrow">↓</span><strong>${escapeHtml(formatRate(system.network_rx_bps).replace("/s", ""))}</strong><small>received</small></div><div><span class="upload-arrow">↑</span><strong>${escapeHtml(formatRate(system.network_tx_bps).replace("/s", ""))}</strong><small>sent</small></div></div><div class="network-bar"><span style="width:70%"></span><i style="width:30%"></i></div><div class="metric-foot"><span>Downlink</span><span>Uplink</span></div></article>
  </section>
  <section class="dashboard-grid">
    <article class="panel machines-panel"><div class="panel-header"><div><h3>Machines</h3><p>Controller and connected remote workers</p></div><button class="text-button" type="button" data-view="machines">View all →</button></div>${machineTable(data)}</article>
    <article class="panel attention-panel"><div class="panel-header compact"><div><h3>Needs attention</h3><p>Alerts and open todos</p></div><span class="count-badge">${alerts.length + openTodos}</span></div><div class="attention-list">${alertItems(alerts)}</div><button class="full-width-link" type="button" data-view="activity">Open alerts & activity</button></article>
  </section>
  <section class="dashboard-grid lower-grid">
    <article class="panel workloads-panel"><div class="panel-header"><div><h3>Active workloads</h3><p>Tracked jobs and persistent shell sessions</p></div><button class="text-button" type="button" data-view="workloads">View all →</button></div><div class="workload-list">${workloadRows(data)}</div><button class="full-width-link" type="button" data-view="workloads">View all ${activeJobs + sessions} workloads</button></article>
    <article class="panel activity-panel"><div class="panel-header compact"><div><h3>Recent activity</h3><p>Latest MCP calls across all nodes</p></div><span class="tag">${version}</span></div><div class="activity-list">${activityRows(data.activity || [])}</div><button class="full-width-link" type="button" data-view="activity">Open audit activity</button></article>
  </section>`
}

function machinesTemplate(data: DashboardData): string {
  return `<section class="page-stack"><article class="panel page-panel"><div class="panel-header"><div><h3>All machines</h3><p>Controller and remote workers with live connectivity and capabilities</p></div><span class="count-badge">${data.machines?.counts?.total ?? data.machines?.machines?.length ?? 0}</span></div>${machineTable(data, true)}</article></section>`
}

function workloadsTemplate(data: DashboardData): string {
  const count = (data.jobs?.length || 0) + (data.session_count ?? data.sessions?.length ?? 0)
  return `<section class="page-stack"><article class="panel page-panel"><div class="panel-header"><div><h3>Active workloads</h3><p>Tracked jobs and persistent terminal sessions</p></div><span class="count-badge">${count}</span></div><div class="workload-list">${workloadRows(data, 100)}</div></article></section>`
}

function activityTemplate(data: DashboardData): string {
  const alerts = data.alerts || []
  const alertCards = alerts.length ? alerts.map((alert) => {
    const severity = stringValue(alert.severity, "info")
    return `<div class="alert-card ${escapeHtml(severity)}"><div class="attention-icon">${severity === "warning" || severity === "critical" ? ICONS.warning : ICONS.info}</div><div><strong>${escapeHtml(alert.title || "Notice")}</strong><p>${escapeHtml(alert.detail || "No additional detail")}</p></div><time>${relativeTime(undefined, alert.age_s)}</time></div>`
  }).join("") : '<div class="empty-state">No active alerts.</div>'
  return `<section class="page-stack"><article class="panel"><div class="panel-header"><div><h3>Alerts</h3><p>Conditions reported by the controller and workers</p></div><span class="count-badge">${alerts.length}</span></div><div class="alert-list-full">${alertCards}</div></article><article class="panel page-panel"><div class="panel-header"><div><h3>Recent MCP activity</h3><p>${data.audit_total_24h || 0} calls matched in the last 24 hours</p></div></div><div class="activity-list">${activityRows(data.activity || [], 100)}</div></article></section>`
}

function todosTemplate(data: BootstrapData | null): string {
  const todos = data?.todos?.todos || []
  const rows = todos.length ? todos.map((todo) => {
    const status = stringValue(todo.status, "open")
    const priority = stringValue(todo.priority, "normal")
    const title = stringValue(todo.title) || stringValue(todo.text) || stringValue(todo.description) || "Untitled todo"
    const detail = stringValue(todo.description) || stringValue(todo.notes) || status
    return `<div class="todo-row ${status === "completed" ? "completed" : ""}"><div class="todo-check">${status === "completed" ? ICONS.check : '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/></svg>'}</div><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></div><span class="priority-chip ${priority === "high" ? "high" : ""}">${escapeHtml(priority)}</span></div>`
  }).join("") : '<div class="empty-state">No todos have been created.</div>'
  return `<section class="page-stack"><article class="panel page-panel"><div class="panel-header"><div><h3>Todos</h3><p>Persistent operational notes shared with MCP</p></div><span class="count-badge">${todos.length}</span></div><div class="todo-list">${rows}</div></article></section>`
}

const PAGE_COPY: Record<Exclude<WebViewName, "console">, { name: string; title: string; description: string }> = {
  overview: { name: "Overview", title: "Control plane overview", description: "System health across your local and remote machines." },
  machines: { name: "Machines", title: "Machines", description: "Connectivity, versions, capabilities, and resource snapshots." },
  workloads: { name: "Workloads", title: "Active workloads", description: "Tracked jobs and persistent shell sessions." },
  activity: { name: "Activity", title: "Alerts & activity", description: "Recent MCP calls and conditions that need attention." },
  todos: { name: "Todos", title: "Operational todos", description: "Persistent tasks shared between human operators and MCP." },
}

function bindRenderedActions(): void {
  viewRoot.querySelectorAll<HTMLElement>("[data-view]").forEach((element) => {
    element.addEventListener("click", () => showView(element.dataset.view as WebViewName))
  })
}

function renderActiveView(): void {
  if (activeView === "console") return
  const copy = PAGE_COPY[activeView]
  pageName.textContent = copy.name
  pageTitle.textContent = copy.title
  pageDescription.textContent = copy.description
  if (!dashboardData) {
    viewRoot.innerHTML = '<div class="loading-state"><span></span><strong>Loading control plane…</strong></div>'
    return
  }
  if (activeView === "overview") viewRoot.innerHTML = overviewTemplate(dashboardData)
  else if (activeView === "machines") viewRoot.innerHTML = machinesTemplate(dashboardData)
  else if (activeView === "workloads") viewRoot.innerHTML = workloadsTemplate(dashboardData)
  else if (activeView === "activity") viewRoot.innerHTML = activityTemplate(dashboardData)
  else viewRoot.innerHTML = todosTemplate(bootstrapData)
  bindRenderedActions()
}

function showView(
  view: WebViewName,
  { syncHash = true, replaceHash = false }: { syncHash?: boolean; replaceHash?: boolean } = {},
): void {
  activeView = view
  if (view !== "console") lastWebView = view
  document.querySelectorAll<HTMLButtonElement>(".nav-item[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view)
  })
  const mode = interfaceModeForView(view)
  interfaceButtons.forEach((button) => {
    const active = button.dataset.interfaceMode === mode
    button.classList.toggle("active", active)
    button.setAttribute("aria-pressed", String(active))
  })
  if (view === "console") {
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
  const machineCount = data.machines?.counts?.total ?? machines.length
  const workloadCount = (data.jobs?.length || 0) + (data.session_count ?? data.sessions?.length ?? 0)
  machineNavCount.textContent = String(machineCount)
  workloadNavCount.textContent = String(workloadCount)
  todoNavCount.textContent = String(data.todo_counts?.open || 0)
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
    dashboardData = dashboard
    syncChrome(dashboard)
    renderActiveView()
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
  refreshTimer = window.setInterval(() => void refreshAll(false), 5_000)
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

let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
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
  terminal.clear()
  terminal.write("\x1b[38;2;117;104;232mStarting local-shell-mcp OpenTUI…\x1b[0m\r\n")
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
      setConnection("error", "Authentication required")
      authGate.hidden = false
      appShell.hidden = true
      stopRefreshTimer()
      return
    }
    if (event.code === 4410) {
      manualDisconnect = true
      setConnection("error", "Disconnected")
      terminal?.write("\r\n\x1b[38;2;255;204;102mThe TUI exited. Use Reconnect to start a new session.\x1b[0m\r\n")
      return
    }
    if ([1011, 4400, 4408, 4429].includes(event.code)) {
      manualDisconnect = true
      setConnection("error", "Disconnected")
      terminal?.write(`\r\n\x1b[38;2;255;123;139m${event.reason || "The OpenTUI session could not continue."}\x1b[0m\r\n`)
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
      background: "#0d1422",
      foreground: "#edf3ff",
      cursor: "#7568e8",
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
  terminal.onData((data) => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(encoder.encode(data))
  })
  terminal.onBinary((data) => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(Uint8Array.from(data, (character: string) => character.charCodeAt(0) & 0xff))
  })
  const touchSequences: Record<string, string> = { escape: "\u001b", tab: "\t", left: "\u001b[D", up: "\u001b[A", down: "\u001b[B", right: "\u001b[C", enter: "\r", help: "\u001bOP" }
  touchButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.key || ""
      if (key === "keyboard") {
        setTouchKeyboard(!touchKeyboardEnabled)
        return
      }
      const sequence = touchSequences[key]
      if (sequence && socket?.readyState === WebSocket.OPEN) socket.send(encoder.encode(sequence))
      if (!usesTouchKeyboard() || touchKeyboardEnabled) terminal?.focus()
      else terminal?.textarea?.blur()
    })
  })
  terminalElement.addEventListener("pointerdown", updatePointerMode, { capture: true })
  touchButtons.forEach((button) => {
    button.addEventListener("pointerdown", updatePointerMode, { capture: true })
  })
  terminalElement.addEventListener("pointerup", () => {
    if (!usesTouchKeyboard() || touchKeyboardEnabled) return
    window.requestAnimationFrame(() => terminal?.textarea?.blur())
  })
  setTouchKeyboard(false)
  terminal.textarea?.addEventListener("focus", () => {
    if (!usesTouchKeyboard() || touchKeyboardEnabled) return
    terminal?.textarea?.blur()
  })
  const resizeObserver = new ResizeObserver(() => window.requestAnimationFrame(sendResize))
  resizeObserver.observe(terminalElement)
  connectTerminal()
}

async function copyTerminalSelection(): Promise<void> {
  const selection = terminal?.getSelection()
  if (!selection) return
  await navigator.clipboard.writeText(selection).catch(() => undefined)
}

window.addEventListener("keydown", (event) => {
  if (activeView !== "console" || !terminal) return
  const selectionShortcut = browserSelectionShortcut(event)
  if (selectionShortcut) {
    event.preventDefault()
    event.stopImmediatePropagation()
    if (selectionShortcut === "select-all") terminal.selectAll()
    else void copyTerminalSelection()
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
    showView(button.dataset.interfaceMode === "tui" ? "console" : lastWebView)
  })
})
loginButton.addEventListener("click", () => void startOAuth("console"))
loginWebButton.addEventListener("click", () => void startOAuth("overview"))
refreshButton.addEventListener("click", () => void refreshAll(true))
openConsoleButton.addEventListener("click", () => showView("console"))
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
