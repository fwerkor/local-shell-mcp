import {
  App,
  applyDocumentTheme,
  applyHostFonts,
  applyHostStyleVariables,
} from "@modelcontextprotocol/ext-apps"
import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import {
  activityDestination,
  activityEventKey,
  activityIntent,
  basename,
  coalesceActivityEvents,
  continuationCountdownState,
  continuationDispatchStillValid,
  escapeHtml,
  eventDetail,
  eventTitle,
  eventTone,
  formatBytes,
  formatClock,
  formatCountdown,
  isOperationalActivityEvent,
  joinPath,
  mergeActivityEvents,
  toggleWorkspaceDisplayMode,
  parentPath,
  reconnectDelayMs,
  renderDiffHtml,
  toolResultFromOpenAiGlobals,
  truncateContext,
  type DisplayMode,
  type LiveEvent,
} from "./live-workspace-utils"

type JsonRecord = Record<string, unknown>

class LiveApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "LiveApiError"
    this.status = status
  }
}

function isLiveCredentialError(error: unknown): boolean {
  return error instanceof LiveApiError && (error.status === 401 || error.status === 403)
}

function waitForRetry(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

type Machine = { name: string; status?: string; workdir?: string; version?: string; platform?: string }
type TerminalSession = { session_id: string; backend?: string; created?: number; attached?: number; cwd?: string; name?: string }
type FileEntry = { name: string; path: string; type: string; size?: number; modified?: number; hidden?: boolean }

type PlanStep = { id: string; text: string; status: "pending" | "active" | "completed" | "skipped"; note?: string }
type PlanState = {
  plan_id: string
  objective: string
  status: "active" | "blocked" | "completed" | "cancelled"
  steps: PlanStep[]
  revision: number
  note?: string | null
  continuation_count: number
  continuation_pending: boolean
  continuation_claim_id?: string | null
  last_agent_activity: number
  execution_lease_s: number
  continuation_due_at: number
  continuation_due: boolean
  continuation_retry_after?: number | null
  max_continuations: number
  auto_continue_exhausted: boolean
  in_flight_calls?: number
}

type LogicalSessionState = {
  session_id: string
  label?: string | null
  objective?: string | null
  status: string
  active_run?: { run_id?: string; status?: string } | null
  progress?: {
    summary?: string | null
    findings?: string[]
    next?: string | null
    blockers?: string[]
    updated_at?: number | null
  }
  recent_activity?: LiveEvent[]
  plan?: PlanState | null
}

type LiveConfig = {
  token: string
  apiBase: string
  uiPath: string
  liveId: string
  sessionId: string
  machine: string
  cwd: string
}

type Dashboard = {
  health?: string
  system?: JsonRecord
  machines?: { machines?: Machine[]; counts?: JsonRecord }
  jobs?: JsonRecord[]
  sessions?: JsonRecord[]
  session_count?: number
  activity?: JsonRecord[]
  alerts?: JsonRecord[]
  version?: JsonRecord
}

const app = new App(
  { name: "local-shell-mcp-live-workspace", version: "1.0.0" },
  { availableDisplayModes: ["pip", "fullscreen"] },
)

type DshBootstrap = {
  sessionId: string
  configEndpoint: string
}

type DshWindow = Window & {
  __LSM_DSH_BOOTSTRAP__?: DshBootstrap
}

const dshBootstrap = (window as DshWindow).__LSM_DSH_BOOTSTRAP__ || null
const isDshHost = dshBootstrap !== null

const root = document.createElement("div")
root.id = "live-workspace-root"
document.body.append(root)

let config: LiveConfig | null = null
let events: LiveEvent[] = []
let cursor = 0
let pollGeneration = 0
let connected = false
let connectionMessage = "Waiting for Live Workspace…"
let activeTab = "activity"
let displayMode: DisplayMode = isDshHost ? "fullscreen" : "pip"
let bootstrap: JsonRecord | null = null
let dashboard: Dashboard | null = null
let machines: Machine[] = []
let lastPassiveRefresh = 0
let passiveRefreshing = false
let coreRefreshQueued = false
let plan: PlanState | null = null
let logicalSession: LogicalSessionState | null = null
let continuationChecking = false
let continuationClaimId = ""
type ContinuationDispatch = {
  claimId: string
  validatedAgentActivity: number
  controller: AbortController
  invalidationReason: string
}
let continuationDispatch: ContinuationDispatch | null = null
let activityExpandedEventKey = ""
const activityAuditDetails = new Map<string, JsonRecord>()
let activityDetailRevision = 0
let activityDiscoveryInitialized = false
let knownActiveJobs = new Set<string>()
let knownStandaloneSessions = new Set<string>()
let shuttingDown = false
let passiveRefreshTimer: number | null = null
let planContinuationTimer: number | null = null
let countdownRenderTimer: number | null = null
let dshModelContext = ""
let dshPromptSequence = 0
const dshPromptWaiters = new Map<string, {
  resolve: (value: JsonRecord) => void
  reject: (error: Error) => void
  timer: number
}>()

let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let terminalSocket: WebSocket | null = null
let terminalResizeObserver: ResizeObserver | null = null
let terminalMachine = "local"
let terminalSessions: TerminalSession[] = []
let selectedSession = ""

let fileMachine = "local"
let filePath = "."
let fileEntries: FileEntry[] = []
let selectedFile = ""
let filePreview: JsonRecord | null = null
let fileEditing = false
let fileEditContent = ""
let fileEditSha = ""

let workloadMachine = "local"
let diffMachine = "local"
let diffCwd = "."
let gitSnapshot: { machine?: string; cwd: string; status: JsonRecord; diff: JsonRecord } | null = null
let auditEntries: JsonRecord[] = []
let remoteSnapshot: JsonRecord | null = null

function icon(name: string): string {
  const paths: Record<string, string> = {
    activity: '<path d="M4 12h3l2-6 4 12 2-6h5"/>',
    terminal: '<path d="m5 7 4 4-4 4M11 15h7"/>',
    files: '<path d="M4 5h6l2 2h8v12H4z"/>',
    diff: '<path d="M7 4v16M4 7h6M14 8h6M17 5v6M14 17h6"/>',
    jobs: '<path d="M4 7h16v11H4zM8 7V4h8v3M8 12h8"/>',
    remotes: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    audit: '<path d="M5 3h14v18H5zM8 8h8M8 12h8M8 16h5"/>',
    expand: '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>',
    pip: '<rect x="3" y="4" width="18" height="16" rx="2"/><rect x="11" y="11" width="7" height="5" rx="1"/>',
    refresh: '<path d="M20 6v5h-5M4 18v-5h5M18 9a7 7 0 0 0-12-2M6 15a7 7 0 0 0 12 2"/>',
    copy: '<rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    chat: '<path d="M4 5h16v11H9l-5 4z"/>',
  }
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.activity}</svg>`
}

function shell(): void {
  root.innerHTML = `
    <div class="live-shell">
      <header class="topbar">
        <div class="brand-area">
          <div class="brand-mark"><svg class="brand-logo" viewBox="0 0 256 256" aria-hidden="true"><defs><linearGradient id="lsm-surface" x1="40" y1="36" x2="218" y2="222" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#8B5CF6"/><stop offset="0.48" stop-color="#6366F1"/><stop offset="1" stop-color="#2563EB"/></linearGradient><linearGradient id="lsm-glow" x1="72" y1="64" x2="196" y2="176" gradientUnits="userSpaceOnUse"><stop stop-color="#FFFFFF" stop-opacity="0.28"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient></defs><rect x="20" y="20" width="216" height="216" rx="54" fill="url(#lsm-surface)"/><path d="M55 20h127c30 0 54 24 54 54v25C184 57 119 40 55 52V20Z" fill="url(#lsm-glow)"/><rect x="20.75" y="20.75" width="214.5" height="214.5" rx="53.25" fill="none" stroke="#FFFFFF" stroke-opacity="0.2" stroke-width="1.5"/><path d="M63 83L103 116L63 149" fill="none" stroke="#FFFFFF" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/><path d="M103 158H137" fill="none" stroke="#FFFFFF" stroke-width="13" stroke-linecap="round"/><path d="M152 112L184 82M156 118L197 124M153 124L180 167" fill="none" stroke="#FFFFFF" stroke-opacity="0.76" stroke-width="6" stroke-linecap="round"/><circle cx="151" cy="117" r="11" fill="#FFFFFF"/><circle cx="188" cy="78" r="10" fill="#FFFFFF"/><circle cx="203" cy="125" r="10" fill="#FFFFFF"/><circle cx="184" cy="174" r="10" fill="#FFFFFF"/><circle cx="151" cy="117" r="4" fill="#6366F1"/><circle cx="188" cy="78" r="3.5" fill="#6366F1"/><circle cx="203" cy="125" r="3.5" fill="#4F63EE"/><circle cx="184" cy="174" r="3.5" fill="#4268ED"/></svg></div>
          <div class="brand-copy">
            <div class="title-row"><strong>Live Workspace</strong><span class="connection-dot" data-role="connection-dot"></span><span data-role="connection-label">${escapeHtml(connectionMessage)}</span></div>
            <div class="subtitle" data-role="subtitle">local-shell-mcp · real-time execution</div>
          </div>
        </div>
        <div class="top-actions">
          <button class="icon-button" data-action="expand" title="Fullscreen">${icon("expand")}</button>
        </div>
      </header>
      <section class="status-strip">
        <div class="current-operation"><span class="pulse" data-role="op-pulse"></span><div><small>Current</small><strong data-role="current-op">No active tool call</strong><span data-role="current-detail">Waiting for activity</span></div></div>
        <div class="status-stat compact-stat"><small>Machines</small><strong data-role="machine-count">—</strong></div>
        <div class="status-stat compact-stat"><small>Workload</small><strong data-role="workload-count">—</strong></div>
      </section>
      <nav class="tabs" aria-label="Workspace views">
        ${tabButton("activity", "Activity")}${tabButton("terminal", "Terminal")}${tabButton("files", "Files")}${tabButton("diff", "Diff")}${tabButton("jobs", "Jobs")}${tabButton("remotes", "Remotes")}${tabButton("audit", "Audit")}
      </nav>
      <main class="workspace-main" data-role="main"><div class="loading"><span></span>${escapeHtml(connectionMessage)}</div></main>
      <div class="toast-stack" data-role="toasts" aria-live="polite"></div>
      <dialog class="live-dialog" data-role="dialog"><form method="dialog"><h3 data-role="dialog-title"></h3><p data-role="dialog-description"></p><label data-role="dialog-label"><span></span><input data-role="dialog-input"/></label><menu><button value="cancel">Cancel</button><button class="primary" value="confirm">Continue</button></menu></form></dialog>
    </div>`
  root.addEventListener("click", onRootClick)
  updateChrome()
}

function tabButton(name: string, label: string): string {
  return `<button data-tab="${name}" class="${activeTab === name ? "active" : ""}">${icon(name)}<span>${label}</span></button>`
}

function qs<T extends Element>(selector: string): T | null {
  return root.querySelector<T>(selector)
}

function currentHostContext(): JsonRecord {
  if (isDshHost) {
    return { displayMode: "fullscreen", availableDisplayModes: [] }
  }
  return (app.getHostContext() || {}) as JsonRecord
}

function onDshPromptResult(event: MessageEvent): void {
  if (!isDshHost || event.source !== window.parent || event.origin !== window.location.origin) return
  const data = event.data as JsonRecord | null
  if (!data || data.type !== "local-shell-mcp:dsh:prompt-result") return
  const requestId = String(data.requestId || "")
  const waiter = dshPromptWaiters.get(requestId)
  if (!waiter) return
  dshPromptWaiters.delete(requestId)
  window.clearTimeout(waiter.timer)
  if (data.ok === true) waiter.resolve(data)
  else waiter.reject(new Error(String(data.message || "DSH rejected the Live Workspace message")))
}

function sendDshPrompt(text: string, signal?: AbortSignal): Promise<JsonRecord> {
  if (!dshBootstrap) return Promise.reject(new Error("DSH Live Workspace bridge is unavailable"))
  if (signal?.aborted) return Promise.reject(new DOMException("The operation was aborted", "AbortError"))
  const requestId = `${Date.now().toString(36)}-${(++dshPromptSequence).toString(36)}`
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      if (!dshPromptWaiters.delete(requestId)) return
      reject(new Error("DSH did not acknowledge the Live Workspace message"))
    }, 30_000)
    const waiter = { resolve, reject, timer }
    dshPromptWaiters.set(requestId, waiter)
    signal?.addEventListener("abort", () => {
      if (dshPromptWaiters.get(requestId) !== waiter) return
      dshPromptWaiters.delete(requestId)
      window.clearTimeout(timer)
      reject(new DOMException("The operation was aborted", "AbortError"))
    }, { once: true })
    window.parent.postMessage({
      type: "local-shell-mcp:dsh:prompt",
      requestId,
      sessionId: dshBootstrap.sessionId,
      text,
    }, window.location.origin)
  })
}

async function updateHostModelContext(
  payload: Parameters<typeof app.updateModelContext>[0],
): Promise<unknown> {
  if (!isDshHost) return await app.updateModelContext(payload)
  dshModelContext = payload.content
    ?.filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("\n\n") || ""
  return {}
}

async function sendHostMessage(
  payload: Parameters<typeof app.sendMessage>[0],
  options?: Parameters<typeof app.sendMessage>[1],
): Promise<unknown> {
  if (!isDshHost) return await app.sendMessage(payload, options)
  const messageText = payload.content
    .filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("\n\n")
  const text = dshModelContext ? `${dshModelContext}\n\n${messageText}` : messageText
  dshModelContext = ""
  await sendDshPrompt(text, options?.signal)
  return { isError: false }
}

function notify(message: string, tone: "info" | "success" | "warning" | "danger" = "info"): void {
  const host = qs<HTMLElement>("[data-role=toasts]")
  if (!host) return
  const item = document.createElement("div")
  item.className = `toast ${tone}`
  item.textContent = message
  host.append(item)
  setTimeout(() => item.classList.add("show"), 10)
  setTimeout(() => {
    item.classList.remove("show")
    setTimeout(() => item.remove(), 180)
  }, 3600)
}

async function promptValue(title: string, label: string, initial = "", description = ""): Promise<string | null> {
  const dialog = qs<HTMLDialogElement>("[data-role=dialog]")
  if (!dialog) return null
  const titleNode = dialog.querySelector<HTMLElement>("[data-role=dialog-title]")
  const descriptionNode = dialog.querySelector<HTMLElement>("[data-role=dialog-description]")
  const labelNode = dialog.querySelector<HTMLElement>("[data-role=dialog-label] span")
  const input = dialog.querySelector<HTMLInputElement>("[data-role=dialog-input]")
  if (!titleNode || !descriptionNode || !labelNode || !input) return null
  titleNode.textContent = title
  descriptionNode.textContent = description
  descriptionNode.hidden = !description
  labelNode.textContent = label
  input.value = initial
  return await new Promise((resolve) => {
    const close = () => {
      dialog.removeEventListener("close", close)
      resolve(dialog.returnValue === "confirm" ? input.value : null)
    }
    dialog.addEventListener("close", close)
    dialog.showModal()
    setTimeout(() => input.focus(), 0)
  })
}

function updateChrome(): void {
  qs<HTMLElement>("[data-role=connection-dot]")?.classList.toggle("connected", connected)
  const connectionLabel = qs<HTMLElement>("[data-role=connection-label]")
  if (connectionLabel) connectionLabel.textContent = connectionMessage
  const subtitle = qs<HTMLElement>("[data-role=subtitle]")
  if (subtitle) subtitle.textContent = config?.sessionId
    ? `local-shell-mcp · session ${config.sessionId}`
    : "local-shell-mcp · no logical session attached"
  root.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === activeTab)
  })
  const expandButton = qs<HTMLButtonElement>("[data-action=expand]")
  if (expandButton) {
    if (isDshHost) {
      expandButton.hidden = true
      expandButton.disabled = true
      expandButton.style.display = "none"
      expandButton.setAttribute("aria-hidden", "true")
    } else {
      expandButton.style.removeProperty("display")
      const fullscreen = displayMode === "fullscreen"
      const targetMode = toggleWorkspaceDisplayMode(displayMode)
      const available = (currentHostContext().availableDisplayModes as string[] | undefined) || []
      const supported = available.includes(targetMode)
      expandButton.classList.toggle("active", fullscreen)
      expandButton.disabled = !supported
      expandButton.title = supported
        ? fullscreen ? "Return to floating window" : "Fullscreen"
        : fullscreen ? "Floating window unavailable in this host" : "Fullscreen unavailable in this host"
      expandButton.setAttribute("aria-label", expandButton.title)
    }
  }

  const running = currentRunningEvent()
  const activeJob = dashboard?.jobs?.[0]
  const activeSession = dashboard?.sessions?.[0]
  const current = qs<HTMLElement>("[data-role=current-op]")
  const detail = qs<HTMLElement>("[data-role=current-detail]")
  const pulse = qs<HTMLElement>("[data-role=op-pulse]")
  if (current) {
    if (running) current.textContent = activityIntent(running)
    else if (activeJob) current.textContent = `Background: ${String(activeJob.name || activeJob.job_id || "job")}`
    else if (activeSession) current.textContent = `Terminal: ${String(activeSession.name || activeSession.session_id || "session")}`
    else current.textContent = "Idle"
  }
  if (detail) {
    if (running) detail.textContent = eventDetail(running) || "In progress"
    else if (activeJob) detail.textContent = String(activeJob.command || activeJob.status || "running")
    else if (activeSession) detail.textContent = String(activeSession.cwd || activeSession.backend || "ready")
    else detail.textContent = latestCompletedSummary()
  }
  pulse?.classList.toggle("active", Boolean(running || activeJob))

  const machineCount = qs<HTMLElement>("[data-role=machine-count]")
  const online = machines.filter((item) => item.status === "online" || item.name === "local").length
  if (machineCount) machineCount.textContent = `${machines.length || 1} · ${online || 1} online`
  const workload = (dashboard?.jobs?.length || 0) + (dashboard?.session_count || dashboard?.sessions?.length || 0)
  const workloadCount = qs<HTMLElement>("[data-role=workload-count]")
  if (workloadCount) workloadCount.textContent = workload ? `${workload} active` : "0"

}

function operationalEvents(): LiveEvent[] {
  return events.filter(isOperationalActivityEvent)
}

function currentRunningEvent(): LiveEvent | null {
  const visible = coalesceActivityEvents(operationalEvents())
  for (let index = visible.length - 1; index >= 0; index -= 1) {
    const event = visible[index]
    if (event.type === "tool.started") return event
  }
  return null
}

function latestCompletedSummary(): string {
  const visible = coalesceActivityEvents(operationalEvents())
  for (let index = visible.length - 1; index >= 0; index -= 1) {
    const event = visible[index]
    if (["tool.completed", "tool.failed", "tool.cancelled", "tool.blocked", "human.action"].includes(event.type)) return activityIntent(event)
  }
  return connected ? "Ready" : "Waiting for connection"
}

function onRootClick(event: MouseEvent): void {
  if ((event.target as HTMLElement).closest(".timeline-detail")) return
  const target = (event.target as HTMLElement).closest<HTMLElement>("[data-tab],[data-action]")
  if (!target) return
  if (target.dataset.tab) void switchTab(target.dataset.tab)
  if (target.dataset.action) void handleAction(target.dataset.action, target)
}

async function handleAction(action: string, target: HTMLElement): Promise<void> {
  try {
    if (action === "expand") await requestDisplayMode(toggleWorkspaceDisplayMode(displayMode))
    else if (action === "refresh") await refreshCurrent(true)
    else if (action === "activity-ask") await askAboutLatestActivity()
    else if (action === "plan-pause") await controlPlan("pause")
    else if (action === "plan-resume") await controlPlan("resume")
    else if (action === "plan-cancel") await controlPlan("cancel")
    else if (action === "plan-cancel-countdown") await controlPlan("pause", "Auto continuation cancelled by user")
    else if (action === "activity-open-detail") await toggleActivityDetail(target.dataset.eventKey || "", target.dataset.callId || "")
    else if (action === "activity-open-terminal") {
      terminalMachine = target.dataset.machine || "local"
      selectedSession = target.dataset.session || ""
      await switchTab("terminal")
    }
    else if (action === "activity-open-jobs") {
      workloadMachine = target.dataset.machine || "local"
      await switchTab("jobs")
    }
    else if (action === "activity-open-files") {
      const path = target.dataset.path || ""
      const tool = target.dataset.tool || ""
      fileMachine = target.dataset.machine || "local"
      if (path) {
        if (["file_list", "file_tree", "file_glob", "file_grep", "list_files", "tree_view", "glob_search", "grep_search", "search"].includes(tool)) {
          filePath = path
          selectedFile = ""
        } else {
          filePath = parentPath(path)
          selectedFile = path
        }
      }
      await switchTab("files")
      if (selectedFile && fileEntries.some((entry) => entry.path === selectedFile)) await selectFile(selectedFile)
    }
    else if (action === "activity-open-diff") {
      diffMachine = target.dataset.machine || "local"
      diffCwd = target.dataset.cwd || config?.cwd || "."
      gitSnapshot = null
      await switchTab("diff")
    }
    else if (action === "activity-open-remotes") await switchTab("remotes")
    else if (action === "activity-open-audit") await switchTab("audit")
    else if (action === "terminal-new") await newTerminal()
    else if (action === "terminal-kill") await killTerminal()
    else if (action === "terminal-copy") await copyTerminal()
    else if (action === "terminal-ctrl-c") sendTerminal("\u0003")
    else if (action === "terminal-reconnect") connectTerminal()
    else if (action === "file-up") { filePath = parentPath(filePath); selectedFile = ""; await refreshFiles() }
    else if (action === "file-new") await createFile(false)
    else if (action === "file-new-dir") await createFile(true)
    else if (action === "file-delete") await deleteSelectedFile()
    else if (action === "file-edit") await beginFileEdit()
    else if (action === "file-save") await saveFileEdit()
    else if (action === "file-cancel-edit") { fileEditing = false; renderFiles() }
    else if (action === "file-context") await shareSelectedFile(false)
    else if (action === "file-ask") await shareSelectedFile(true)
    else if (action === "diff-context") await shareDiff(false)
    else if (action === "diff-ask") await shareDiff(true)
    else if (action === "remote-invite") await createRemoteInvite()
    else if (action === "remote-rename") await renameRemote(target.dataset.machine || "")
    else if (action === "remote-revoke") await revokeRemote(target.dataset.machine || "")
    else if (action === "audit-ask") await askAboutAudit(target.dataset.id || "")
  } catch (error) {
    notify(error instanceof Error ? error.message : String(error), "danger")
  }
}

async function requestDisplayMode(mode: "fullscreen" | "pip"): Promise<void> {
  if (isDshHost) return
  try {
    const result = await app.requestDisplayMode({ mode })
    if (result.mode === "pip" || result.mode === "fullscreen") displayMode = result.mode
    document.documentElement.dataset.displayMode = displayMode
    updateChrome()
  } catch (error) {
    notify(`Host did not change display mode: ${error instanceof Error ? error.message : String(error)}`, "warning")
  }
}

async function controlPlan(action: "pause" | "resume" | "cancel", note?: string): Promise<void> {
  if (!config || !plan) return
  if (action === "pause" || action === "cancel") {
    abortContinuationDispatch(`Goal ${action === "pause" ? "paused" : "cancelled"} by user`)
  }
  const payload = await api<{ goal_mode: boolean; plan: PlanState }>("/api/live/plan", {
    method: "POST",
    body: JSON.stringify({ action, ...(note ? { note } : {}) }),
  })
  plan = payload.plan
  if (logicalSession) logicalSession = { ...logicalSession, plan }
  renderCurrentTab()
  notify(
    action === "pause" ? "Goal paused" : action === "resume" ? "Goal resumed" : "Goal cancelled",
    action === "cancel" ? "warning" : "success",
  )
}

function abortContinuationDispatch(reason: string): void {
  const dispatch = continuationDispatch
  if (!dispatch || dispatch.controller.signal.aborted) return
  dispatch.invalidationReason = reason
  dispatch.controller.abort()
}

function observeContinuationPlan(nextPlan: PlanState | null): void {
  const dispatch = continuationDispatch
  if (!dispatch) return
  if (!continuationDispatchStillValid(nextPlan, dispatch.claimId, dispatch.validatedAgentActivity)) {
    abortContinuationDispatch("Continuation became stale before host dispatch completed")
  }
}

async function watchContinuationDispatch(dispatch: ContinuationDispatch): Promise<void> {
  while (!shuttingDown && continuationDispatch === dispatch && !dispatch.controller.signal.aborted) {
    await waitForRetry(500)
    if (continuationDispatch !== dispatch || dispatch.controller.signal.aborted) return
    try {
      const validation = await api<{ valid: boolean; plan?: PlanState | null }>("/api/live/plan/continuation", {
        method: "POST",
        body: JSON.stringify({ action: "validate", claim_id: dispatch.claimId }),
      })
      if (continuationDispatch !== dispatch || dispatch.controller.signal.aborted) return
      const nextPlan = validation.plan || null
      observeContinuationPlan(nextPlan)
      plan = nextPlan || plan
      if (!validation.valid) {
        abortContinuationDispatch("Continuation claim was invalidated before host dispatch completed")
        if (activeTab === "activity") renderActivity()
        return
      }
    } catch (error) {
      abortContinuationDispatch(
        isLiveCredentialError(error)
          ? "Live Workspace authorization changed during continuation dispatch"
          : "Continuation could not be revalidated before host dispatch completed",
      )
      console.warn("Unable to revalidate continuation while dispatching", error)
      return
    }
  }
}

async function switchTab(next: string): Promise<void> {
  if (next === activeTab) return
  if (activeTab === "terminal") destroyTerminal()
  activeTab = next
  updateChrome()
  renderCurrentTab()
  await refreshCurrent(false)
}

function mainNode(): HTMLElement {
  const node = qs<HTMLElement>("[data-role=main]")
  if (!node) throw new Error("Live Workspace root is unavailable")
  return node
}

function renderCurrentTab(): void {
  if (!config) {
    mainNode().innerHTML = `<div class="loading"><span></span>${escapeHtml(connectionMessage)}</div>`
    return
  }
  if (activeTab === "activity") renderActivity()
  else if (activeTab === "terminal") renderTerminal()
  else if (activeTab === "files") renderFiles()
  else if (activeTab === "diff") renderDiff()
  else if (activeTab === "jobs") renderJobs()
  else if (activeTab === "remotes") renderRemotes()
  else renderAudit()
}

function durableSessionEvents(): LiveEvent[] {
  const durable = logicalSession?.recent_activity || []
  return mergeActivityEvents(durable, operationalEvents())
}

function planProgress(): { completed: number; total: number; percent: number; active: PlanStep | null } {
  if (!plan) return { completed: 0, total: 0, percent: 0, active: null }
  const completed = plan.steps.filter((step) => step.status === "completed" || step.status === "skipped").length
  const total = plan.steps.length
  return {
    completed,
    total,
    percent: total ? Math.round((completed / total) * 100) : 0,
    active: plan.steps.find((step) => step.status === "active") || null,
  }
}

function renderActivity(): void {
  const visible = coalesceActivityEvents(durableSessionEvents())
  // Durable Session history keeps 200 raw lifecycle events. Since a normal
  // started/completed pair coalesces into one row, reconnects intentionally
  // restore roughly 100 tool rows; the larger slice also leaves room for
  // live-only and semantic Session/Plan events.
  const recent = [...visible].reverse().slice(0, 200)
  const running = currentRunningEvent()
  const progress = planProgress()
  const sessionStatus = logicalSession?.status || (config?.sessionId ? "active" : "unattached")
  mainNode().innerHTML = `
    <section class="view activity-view task-monitor-view">
      <div class="view-toolbar task-monitor-toolbar"><div><h2>Live task monitor</h2><p>${config?.sessionId ? `Logical Session ${escapeHtml(config.sessionId)}` : "No Logical Session attached yet"}</p></div><div class="toolbar-actions"><button class="button" data-action="activity-ask">${icon("chat")}Ask</button><button class="button" data-action="refresh">${icon("refresh")}Refresh</button></div></div>
      <div class="task-monitor-grid">
        <section class="monitor-card session-monitor-card">
          <div class="monitor-card-head"><span>Session</span><strong class="status-pill ${escapeHtml(sessionStatus)}">${escapeHtml(sessionStatus)}</strong></div>
          <strong class="monitor-primary">${escapeHtml(logicalSession?.label || logicalSession?.objective || (config?.sessionId ? "Active logical task" : "Standard workspace"))}</strong>
          <span class="monitor-secondary">${logicalSession?.active_run?.run_id ? `Run ${escapeHtml(logicalSession.active_run.run_id)}` : config?.sessionId ? "Waiting for active run" : "No extra user action required"}</span>
        </section>
        <section class="monitor-card operation-monitor-card">
          <div class="monitor-card-head"><span>Latest operation</span><strong class="live-dot-label"><i class="live-dot ${running ? "busy" : ""}"></i>${running ? "Running" : connected ? "Live" : "Offline"}</strong></div>
          <strong class="monitor-primary">${escapeHtml(running ? activityIntent(running) : latestCompletedSummary())}</strong>
          <span class="monitor-secondary">${escapeHtml(running ? eventDetail(running) || "Tool call in progress" : recent[0] ? eventTitle(recent[0]) : "Waiting for activity")}</span>
        </section>
        <section class="monitor-card plan-monitor-card">
          <div class="monitor-card-head"><span>Plan progress</span><strong>${plan ? `${progress.percent}%` : "Standard"}</strong></div>
          ${plan ? `<div class="progress-track"><span style="width:${progress.percent}%"></span></div><strong class="monitor-primary">${progress.completed}/${progress.total} steps complete</strong><span class="monitor-secondary">${escapeHtml(progress.active?.text || (plan.status === "completed" ? "Plan completed" : plan.status === "blocked" ? "Plan paused" : "No active step"))}</span>` : '<strong class="monitor-primary">No active plan</strong><span class="monitor-secondary">Session tracking remains active without Goal mode.</span>'}
        </section>
        ${autoContinueCard()}
      </div>
      <div class="task-monitor-body">
        <div class="task-context-column">
          ${sessionProgressPanel()}
          ${planCard()}
          ${activityFocusCards()}
        </div>
        <section class="panel activity-panel session-activity-panel">
          <div class="panel-head"><div><strong>Logical Session activity</strong><small>Durable, live execution feed</small></div><span>${recent.length} recent</span></div>
          <div class="timeline session-timeline">${recent.length ? recent.map(activityRow).join("") : '<div class="empty-state">No execution activity yet. The current task will appear here automatically.</div>'}</div>
        </section>
      </div>
    </section>`
}

function sessionProgressPanel(): string {
  if (!logicalSession) return ""
  const progress = logicalSession.progress || {}
  const findings = progress.findings || []
  const blockers = progress.blockers || []
  if (!progress.summary && !progress.next && !findings.length && !blockers.length) return ""
  return `
    <section class="panel session-progress-panel">
      <div class="panel-head"><div><strong>Session checkpoint</strong><small>Semantic progress reported by the active agent</small></div>${progress.updated_at ? `<span>${escapeHtml(formatClock(progress.updated_at))}</span>` : ""}</div>
      <div class="checkpoint-grid">
        <div><small>Current</small><strong>${escapeHtml(progress.summary || "No summary yet")}</strong></div>
        <div><small>Next</small><strong>${escapeHtml(progress.next || "No next action reported")}</strong></div>
        <div class="${blockers.length ? "has-blocker" : ""}"><small>Blockers</small><strong>${escapeHtml(blockers.length ? blockers.join(" · ") : "None")}</strong></div>
      </div>
      ${findings.length ? `<div class="checkpoint-findings"><small>Findings</small>${findings.slice(0, 6).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    </section>`
}

function autoContinueCard(): string {
  if (!plan) {
    return `<section class="monitor-card auto-monitor-card" data-role="auto-continue-card"><div class="monitor-card-head"><span>Auto continue</span><strong>Off</strong></div><strong class="monitor-primary">Plan mode inactive</strong><span class="monitor-secondary">No continuation timer is needed.</span></section>`
  }
  if (plan.status === "blocked") {
    return `<section class="monitor-card auto-monitor-card paused" data-role="auto-continue-card"><div class="monitor-card-head"><span>Auto continue</span><strong>Paused</strong></div><strong class="monitor-primary">Waiting for you</strong><span class="monitor-secondary">Automatic continuation is disabled while the plan is paused.</span><button class="button compact-monitor-action" data-action="plan-resume">Resume</button></section>`
  }
  if (plan.auto_continue_exhausted) {
    return `<section class="monitor-card auto-monitor-card paused" data-role="auto-continue-card"><div class="monitor-card-head"><span>Auto continue</span><strong>Stopped</strong></div><strong class="monitor-primary">${plan.continuation_count}/${plan.max_continuations} attempts used</strong><span class="monitor-secondary">The automatic continuation cap has been reached.</span></section>`
  }
  if (plan.continuation_pending) {
    return `<section class="monitor-card auto-monitor-card active" data-role="auto-continue-card"><div class="monitor-card-head"><span>Auto continue</span><strong>Triggering</strong></div><strong class="monitor-primary">Continuation requested</strong><span class="monitor-secondary">Handing the same Logical Session to the next agent run.</span></section>`
  }
  if (Number(plan.in_flight_calls || 0) > 0) {
    return `<section class="monitor-card auto-monitor-card" data-role="auto-continue-card"><div class="monitor-card-head"><span>Auto continue</span><strong>Waiting</strong></div><strong class="monitor-primary">Tool call in progress</strong><span class="monitor-secondary">The idle timer does not trigger while work is still running.</span></section>`
  }
  const countdown = continuationCountdownState(plan)
  if (!countdown.visible) {
    const untilVisible = Math.max(0, (5 * 60) - countdown.idleSeconds)
    return `<section class="monitor-card auto-monitor-card" data-role="auto-continue-card"><div class="monitor-card-head"><span>Auto continue</span><strong>Armed</strong></div><strong class="monitor-primary">${plan.continuation_count}/${plan.max_continuations} continuations</strong><span class="monitor-secondary">Countdown appears after 5 min idle${countdown.idleSeconds > 0 ? ` · ${formatCountdown(untilVisible)} until visible` : ""}.</span></section>`
  }
  return `<section class="monitor-card auto-monitor-card countdown" data-role="auto-continue-card"><div class="monitor-card-head"><span>Auto continue</span><strong>Countdown</strong></div><strong class="countdown-time">${escapeHtml(formatCountdown(countdown.remainingSeconds))}</strong><div class="countdown-track"><span style="width:${Math.round(countdown.progress * 100)}%"></span></div><span class="monitor-secondary">until automatic continuation · attempt ${plan.continuation_count + 1}/${plan.max_continuations}</span><button class="button compact-monitor-action" data-action="plan-cancel-countdown">Cancel countdown</button></section>`
}

function refreshAutoContinueCard(): void {
  if (activeTab !== "activity") return
  const node = qs<HTMLElement>('[data-role="auto-continue-card"]')
  if (!node) return
  const replacement = document.createElement("div")
  replacement.innerHTML = autoContinueCard()
  const next = replacement.firstElementChild
  if (next) node.replaceWith(next)
}

function planCard(): string {
  if (!plan || !["active", "blocked"].includes(plan.status)) return ""
  const progress = planProgress()
  const status = plan.status === "blocked" ? "Needs you" : plan.continuation_pending ? "Continuing" : "Active"
  return `
    <section class="goal-card ${escapeHtml(plan.status)} detailed-plan-card">
      <div class="goal-head"><div><small>Plan</small><strong>${escapeHtml(plan.objective)}</strong></div><span class="goal-status">${escapeHtml(status)}</span></div>
      <div class="plan-progress-summary"><div class="progress-track"><span style="width:${progress.percent}%"></span></div><span>${progress.completed}/${progress.total} complete · ${progress.percent}%</span></div>
      ${plan.note ? `<p class="goal-note">${escapeHtml(plan.note)}</p>` : ""}
      <div class="plan-steps">${plan.steps.map((step) => `<div class="plan-step ${escapeHtml(step.status)}"><span class="plan-step-mark">${step.status === "completed" ? "✓" : step.status === "skipped" ? "–" : step.status === "active" ? "→" : "○"}</span><div><strong>${escapeHtml(step.text)}</strong>${step.note ? `<small>${escapeHtml(step.note)}</small>` : ""}</div></div>`).join("")}</div>
      <footer><span>Auto continue ${plan.continuation_count}/${plan.max_continuations}</span><div class="goal-actions">${plan.status === "blocked" ? '<button class="button" data-action="plan-resume">Resume</button>' : '<button class="button" data-action="plan-pause">Pause</button>'}<button class="button danger" data-action="plan-cancel">Cancel plan</button></div></footer>
    </section>`
}

function activityFocusCards(): string {
  const jobs = dashboard?.jobs || []
  const sessions = dashboard?.sessions || []
  if (!jobs.length && !sessions.length) return ""
  const cards: string[] = []
  for (const job of jobs.slice(0, 2)) {
    const sessionId = String(job.session_id || "")
    const action = sessionId ? "activity-open-terminal" : "activity-open-jobs"
    cards.push(`<button class="focus-card job" data-action="${action}" data-session="${escapeHtml(sessionId)}" data-machine="${escapeHtml(String(job.machine || workloadMachine || "local"))}"><small>Background job</small><strong>${escapeHtml(String(job.name || job.job_id || "job"))}</strong><span>${escapeHtml(String(job.status || "running"))} · ${sessionId ? "View output" : "Open jobs"}</span></button>`)
  }
  for (const session of sessions.slice(0, Math.max(0, 3 - cards.length))) {
    cards.push(`<button class="focus-card terminal" data-action="activity-open-terminal" data-session="${escapeHtml(String(session.session_id || ""))}" data-machine="${escapeHtml(String(session.machine || workloadMachine || "local"))}"><small>Persistent terminal</small><strong>${escapeHtml(String(session.name || session.session_id || "terminal"))}</strong><span>Open terminal</span></button>`)
  }
  return `<div class="activity-focus">${cards.join("")}</div>`
}

function activityRow(event: LiveEvent): string {
  const detail = eventDetail(event)
  const destination = activityDestination(event)
  const callId = String(event.data.call_id || "")
  const eventKey = activityEventKey(event)
  let action = ""
  let actionLabel = ""
  if (destination === "terminal") {
    action = `data-action="activity-open-terminal" data-session="${escapeHtml(String(event.data.session_id || ""))}" data-machine="${escapeHtml(String(event.data.machine || "local"))}"`
    actionLabel = "Open terminal"
  } else if (destination === "jobs") {
    action = `data-action="activity-open-jobs" data-machine="${escapeHtml(String(event.data.machine || "local"))}"`
    actionLabel = "Open jobs"
  } else if (destination === "files") {
    const rawPath = event.data.path ?? event.data.cwd
    const path = Array.isArray(rawPath) ? String(rawPath[0] || "") : String(rawPath || "")
    action = `data-action="activity-open-files" data-tool="${escapeHtml(String(event.data.tool || ""))}" data-path="${escapeHtml(path)}" data-machine="${escapeHtml(String(event.data.machine || "local"))}"`
    actionLabel = "Open files"
  } else if (destination === "diff") {
    action = `data-action="activity-open-diff" data-machine="${escapeHtml(String(event.data.machine || "local"))}" data-cwd="${escapeHtml(String(event.data.cwd || config?.cwd || "."))}"`
    actionLabel = "View diff"
  } else if (destination === "remotes") {
    action = `data-action="activity-open-remotes"`
    actionLabel = "Open remotes"
  } else if (destination === "audit") {
    action = `data-action="activity-open-audit"`
    actionLabel = "Open audit"
  } else if (destination === "detail" && callId) {
    action = `data-action="activity-open-detail" data-event-key="${escapeHtml(eventKey)}" data-call-id="${escapeHtml(callId)}"`
    actionLabel = activityExpandedEventKey === eventKey ? "Hide output" : "View output"
  }
  const expanded = callId && activityExpandedEventKey === eventKey ? activityDetailHtml(callId) : ""
  return `<div class="timeline-row ${eventTone(event)} ${action ? "clickable" : ""}" ${action}><div class="timeline-marker"><span></span></div><div class="timeline-copy"><div><strong>${escapeHtml(eventTitle(event))}</strong><span class="actor ${escapeHtml(event.actor)}">${escapeHtml(event.actor)}</span>${actionLabel ? `<span class="timeline-action">${escapeHtml(actionLabel)}</span>` : ""}</div>${detail ? `<p>${escapeHtml(detail)}</p>` : ""}</div><time>${escapeHtml(formatClock(event.ts))}</time>${expanded}</div>`
}

function activityDetailHtml(callId: string): string {
  const detail = activityAuditDetails.get(callId)
  if (!detail) return '<div class="timeline-detail loading-detail">Loading output…</div>'
  const output = detail.output as JsonRecord | undefined
  const structured = (output?.structuredContent || output?.structured_content) as JsonRecord | undefined
  const payload = (structured?.data || output?.data || structured || output || detail) as unknown
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const record = payload as JsonRecord
    const chunks: string[] = []
    if (record.command) chunks.push(`$ ${String(record.command)}`)
    if (record.stdout) chunks.push(String(record.stdout))
    if (record.stderr) chunks.push(`stderr:\n${String(record.stderr)}`)
    if (chunks.length) return `<pre class="timeline-detail">${escapeHtml(truncateContext(chunks.join("\n"), 24_000))}</pre>`
  }
  return `<pre class="timeline-detail">${escapeHtml(truncateContext(JSON.stringify(payload, null, 2), 24_000))}</pre>`
}

async function toggleActivityDetail(eventKey: string, callId: string): Promise<void> {
  if (!eventKey || !callId) return
  if (activityExpandedEventKey === eventKey) {
    activityExpandedEventKey = ""
    renderActivity()
    return
  }
  activityExpandedEventKey = eventKey
  renderActivity()
  if (activityAuditDetails.has(callId)) return
  try {
    const generation = pollGeneration
    while (activityExpandedEventKey === eventKey && generation === pollGeneration) {
      const revision = activityDetailRevision
      const detail = await api<JsonRecord>(`/api/ui/audit/detail?id=${encodeURIComponent(`call:${callId}`)}`)
      if (activityExpandedEventKey !== eventKey || generation !== pollGeneration) return
      if (revision !== activityDetailRevision) continue
      activityAuditDetails.set(callId, detail)
      if (activeTab === "activity") renderActivity()
      return
    }
  } catch (error) {
    if (activityExpandedEventKey === eventKey) activityExpandedEventKey = ""
    if (activeTab === "activity") renderActivity()
    notify(error instanceof Error ? error.message : String(error), "warning")
  }
}

async function askAboutLatestActivity(): Promise<void> {
  const recent = durableSessionEvents().slice(-20)
  await updateHostModelContext({
    content: [{ type: "text", text: `Live Workspace recent operational activity:\n${recent.map((event) => `${formatClock(event.ts)} ${eventTitle(event)} — ${eventDetail(event)}`).join("\n")}` }],
    structuredContent: { liveWorkspaceEvents: recent },
  })
  await sendHostMessage({ role: "user", content: [{ type: "text", text: "Review the recent Live Workspace activity and tell me what matters, especially any failure, blocker, or next action." }] })
}

function renderTerminal(): void {
  const session = terminalSessions.find((item) => item.session_id === selectedSession)
  mainNode().innerHTML = `
    <section class="view terminal-view">
      <div class="view-toolbar terminal-toolbar"><div class="toolbar-left"><label>Machine<select data-role="terminal-machine">${machineOptions(terminalMachine)}</select></label><label>Session<select data-role="terminal-session"><option value="">${terminalSessions.length ? "Select session" : "No sessions"}</option>${terminalSessions.map((item) => `<option value="${escapeHtml(item.session_id)}"${item.session_id === selectedSession ? " selected" : ""}>${escapeHtml(item.name || item.session_id)}</option>`).join("")}</select></label></div><div class="toolbar-actions"><button class="button" data-action="terminal-new">New</button><button class="button" data-action="terminal-kill" ${selectedSession ? "" : "disabled"}>Kill</button><button class="button" data-action="terminal-copy">${icon("copy")}Copy</button><button class="button" data-action="terminal-ctrl-c" ${selectedSession ? "" : "disabled"}>Ctrl-C</button><button class="button" data-action="terminal-reconnect">Reconnect</button></div></div>
      <div class="terminal-card">
        <div class="terminal-title"><div><span class="terminal-led ${selectedSession ? "online" : ""}"></span><strong>${escapeHtml(session?.name || selectedSession || "Persistent terminal")}</strong><small>${escapeHtml(terminalMachine)}${session?.backend ? ` · ${escapeHtml(session.backend)}` : ""}</small></div><span>Collaborative input</span></div>
        <div class="terminal-host" data-role="terminal-host"></div>
        <form class="command-dock" data-role="command-form"><span>$</span><input data-role="command-input" autocomplete="off" placeholder="Send command to attached session" ${selectedSession ? "" : "disabled"}/><button ${selectedSession ? "" : "disabled"}>Send</button></form>
      </div>
    </section>`
  wireTerminalControls()
  mountTerminal()
}

function machineOptions(selected: string): string {
  const rows = machines.length ? machines : [{ name: "local", status: "online" }]
  return rows.map((machine) => `<option value="${escapeHtml(machine.name)}"${machine.name === selected ? " selected" : ""}>${escapeHtml(machine.name)}${machine.status && machine.name !== "local" ? ` · ${escapeHtml(machine.status)}` : ""}</option>`).join("")
}

function wireTerminalControls(): void {
  const machineSelect = qs<HTMLSelectElement>("[data-role=terminal-machine]")
  const sessionSelect = qs<HTMLSelectElement>("[data-role=terminal-session]")
  machineSelect?.addEventListener("change", () => {
    terminalMachine = machineSelect.value
    selectedSession = ""
    void refreshTerminals()
  })
  sessionSelect?.addEventListener("change", () => {
    selectedSession = sessionSelect.value
    renderTerminal()
  })
  const form = qs<HTMLFormElement>("[data-role=command-form]")
  form?.addEventListener("submit", (event) => {
    event.preventDefault()
    const input = qs<HTMLInputElement>("[data-role=command-input]")
    if (!input || !input.value.trim()) return
    sendTerminal(`${input.value}\r`)
    input.value = ""
  })
}

function mountTerminal(): void {
  destroyTerminal()
  const host = qs<HTMLElement>("[data-role=terminal-host]")
  if (!host) return
  terminal = new Terminal({
    allowTransparency: true,
    cursorBlink: true,
    cursorStyle: "bar",
    disableStdin: false,
    fontFamily: 'var(--font-mono, "SFMono-Regular", "Cascadia Code", Consolas, monospace)',
    fontSize: 13,
    lineHeight: 1.18,
    scrollback: 12_000,
    smoothScrollDuration: 60,
    theme: {
      background: "rgba(0,0,0,0)", foreground: "#d8e0ef", cursor: "#8f82ff", selectionBackground: "#65739180",
      black: "#101521", red: "#ff7b8b", green: "#71d6a1", yellow: "#e7b864", blue: "#79a7ff", magenta: "#bd9cff", cyan: "#65d5d0", white: "#e7ecf5",
      brightBlack: "#78849b", brightRed: "#ff9aa6", brightGreen: "#98e5b8", brightYellow: "#f1cd89", brightBlue: "#9ebeff", brightMagenta: "#d6bbff", brightCyan: "#8ee6e2", brightWhite: "#ffffff",
    },
  })
  fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  terminal.open(host)
  terminal.onData((data) => sendTerminal(data))
  terminalResizeObserver = new ResizeObserver(() => requestAnimationFrame(() => fitTerminal()))
  terminalResizeObserver.observe(host)
  requestAnimationFrame(() => fitTerminal())
  if (selectedSession) connectTerminal()
  else terminal.write("\x1b[38;2;143;130;255mSelect or create a persistent session.\x1b[0m\r\n")
}

function fitTerminal(): void {
  if (!terminal || !fitAddon) return
  try { fitAddon.fit() } catch { return }
  if (terminalSocket?.readyState === WebSocket.OPEN) terminalSocket.send(JSON.stringify({ type: "resize", cols: terminal.cols, rows: terminal.rows }))
}

function destroyTerminal(): void {
  terminalSocket?.close()
  terminalSocket = null
  terminalResizeObserver?.disconnect()
  terminalResizeObserver = null
  terminal?.dispose()
  terminal = null
  fitAddon = null
}

function connectTerminal(): void {
  if (!config || !terminal || !selectedSession) return
  terminalSocket?.close()
  terminal.clear()
  terminal.write(`\x1b[38;2;143;130;255mAttaching to ${terminalMachine}:${selectedSession}…\x1b[0m\r\n`)
  const base = new URL(config.apiBase)
  const url = new URL(config.uiPath.replace(/\/$/, "") + "/ws/shell", base)
  url.protocol = base.protocol === "https:" ? "wss:" : "ws:"
  url.searchParams.set("machine", terminalMachine)
  url.searchParams.set("session_id", selectedSession)
  url.searchParams.set("cols", String(terminal.cols))
  url.searchParams.set("rows", String(terminal.rows))
  const socket = new WebSocket(url, ["lsm-ui", bearerProtocol(config.token)])
  socket.binaryType = "arraybuffer"
  terminalSocket = socket
  socket.onopen = () => {
    if (terminalSocket !== socket) return
    fitTerminal()
    notify(`Attached to ${selectedSession}`, "success")
  }
  socket.onmessage = async (event) => {
    if (terminalSocket !== socket || !terminal) return
    if (event.data instanceof ArrayBuffer) terminal.write(new Uint8Array(event.data))
    else if (event.data instanceof Blob) terminal.write(new Uint8Array(await event.data.arrayBuffer()))
    else terminal.write(String(event.data))
  }
  socket.onclose = (event) => {
    if (terminalSocket !== socket) return
    terminalSocket = null
    terminal?.write(`\r\n\x1b[38;2;231;184;100mDisconnected${event.reason ? `: ${event.reason}` : ""}.\x1b[0m\r\n`)
  }
}

function bearerProtocol(token: string): string {
  let binary = ""
  for (const byte of new TextEncoder().encode(token)) binary += String.fromCharCode(byte)
  return `bearer.${btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "")}`
}

function sendTerminal(data: string): void {
  if (!selectedSession) return
  if (terminalSocket?.readyState === WebSocket.OPEN) terminalSocket.send(new TextEncoder().encode(data))
}

async function refreshTerminals(): Promise<void> {
  if (!config) return
  const requestMachine = terminalMachine
  const payload = await api<{ machine: string; sessions: TerminalSession[] }>(`/api/ui/terminals?machine=${encodeURIComponent(requestMachine)}`)
  if (terminalMachine !== requestMachine) return
  terminalSessions = payload.sessions || []
  if (!terminalSessions.some((item) => item.session_id === selectedSession)) selectedSession = terminalSessions[0]?.session_id || ""
  if (activeTab === "terminal") renderTerminal()
}

async function newTerminal(): Promise<void> {
  const name = await promptValue("New terminal", "Optional name", "", `Create a persistent shell on ${terminalMachine}.`)
  if (name === null) return
  const requestMachine = terminalMachine
  const requestCwd = config?.cwd || "."
  const result = await api<JsonRecord>("/api/ui/terminals/start", { method: "POST", body: JSON.stringify({ machine: requestMachine, cwd: requestCwd, name: name || null }) })
  if (terminalMachine !== requestMachine) return
  selectedSession = String(result.session_id || "")
  await refreshTerminals()
}

async function killTerminal(): Promise<void> {
  if (!selectedSession) return
  const requestMachine = terminalMachine
  const requestSession = selectedSession
  await api("/api/ui/terminals/kill", { method: "POST", body: JSON.stringify({ machine: requestMachine, session_id: requestSession }) })
  if (terminalMachine !== requestMachine || selectedSession !== requestSession) return
  selectedSession = ""
  await refreshTerminals()
}

async function copyTerminal(): Promise<void> {
  const text = terminal?.getSelection() || ""
  if (!text) { notify("Select terminal text first", "info"); return }
  await navigator.clipboard.writeText(text)
  notify("Terminal selection copied", "success")
}

function renderFiles(): void {
  const selected = fileEntries.find((entry) => entry.path === selectedFile)
  mainNode().innerHTML = `
    <section class="view files-view">
      <div class="view-toolbar files-toolbar"><div class="path-controls"><label>Machine<select data-role="file-machine">${machineOptions(fileMachine)}</select></label><button class="button" data-action="file-up">Up</button><input data-role="file-path" value="${escapeHtml(filePath)}" aria-label="Path"/></div><div class="toolbar-actions"><button class="button" data-action="file-new">New file</button><button class="button" data-action="file-new-dir">New folder</button><button class="button" data-action="refresh">${icon("refresh")}Refresh</button></div></div>
      <div class="files-grid">
        <section class="panel file-list-panel"><div class="panel-head"><strong>${escapeHtml(fileMachine)}:${escapeHtml(filePath)}</strong><span>${fileEntries.length} entries</span></div><div class="file-list">${fileEntries.length ? fileEntries.map(fileRow).join("") : '<div class="empty-state">Directory is empty.</div>'}</div></section>
        <section class="panel preview-panel"><div class="panel-head"><div><strong>${escapeHtml(selected?.name || "Preview")}</strong><span>${selected ? `${escapeHtml(selected.type)} · ${formatBytes(selected.size)}` : "Choose a file"}</span></div><div class="preview-actions">${selected?.type === "file" ? `${isDshHost ? "" : '<button class="text-button" data-action="file-context">Send context</button>'}<button class="text-button" data-action="file-ask">${isDshHost ? "Ask DSH" : "Ask ChatGPT"}</button><button class="text-button" data-action="file-edit">Edit</button><button class="text-button danger" data-action="file-delete">Delete</button>` : ""}</div></div><div class="file-preview" data-role="file-preview">${renderFilePreview()}</div></section>
      </div>
    </section>`
  wireFileControls()
  if (filePreview?.kind === "image") requestAnimationFrame(drawFileImage)
}

function fileRow(entry: FileEntry): string {
  const selected = entry.path === selectedFile
  return `<button class="file-row ${selected ? "selected" : ""}" data-file="${escapeHtml(entry.path)}"><span class="file-icon ${entry.type}">${entry.type === "dir" ? "⌑" : "·"}</span><span><strong>${escapeHtml(entry.name)}</strong><small>${entry.type === "dir" ? "folder" : formatBytes(entry.size)}</small></span><time>${entry.modified ? new Date(entry.modified * 1000).toLocaleString() : ""}</time></button>`
}

function renderFilePreview(): string {
  if (fileEditing) {
    return `<div class="editor-wrap"><textarea data-role="file-editor" spellcheck="false">${escapeHtml(fileEditContent)}</textarea><div class="editor-actions"><span>Optimistic save checks the original SHA-256.</span><button class="button" data-action="file-cancel-edit">Cancel</button><button class="button primary" data-action="file-save">Save</button></div></div>`
  }
  if (!selectedFile) return '<div class="empty-state">Select a file or folder.</div>'
  if (!filePreview) return '<div class="loading small"><span></span>Loading preview…</div>'
  const kind = String(filePreview.kind || "")
  if (kind === "directory") return `<div class="empty-state">Open the folder to browse its contents.</div>`
  if (kind === "image") return '<div class="image-stage"><canvas data-role="file-image"></canvas><span>Image preview</span></div>'
  if (kind === "binary") return `<pre class="code-preview">${escapeHtml(String(filePreview.preview || "Binary file"))}</pre>`
  return `<pre class="code-preview">${escapeHtml(String(filePreview.content || ""))}</pre>`
}

function drawFileImage(): void {
  if (!filePreview || filePreview.kind !== "image") return
  const canvas = qs<HTMLCanvasElement>("[data-role=file-image]")
  const encoded = String(filePreview.rgba || "")
  const width = Number(filePreview.width || 0)
  const height = Number(filePreview.height || 0)
  if (!canvas || !encoded || !width || !height) return
  const raw = atob(encoded)
  const bytes = Uint8ClampedArray.from(raw, (char) => char.charCodeAt(0))
  canvas.width = width
  canvas.height = height
  canvas.getContext("2d")?.putImageData(new ImageData(bytes, width, height), 0, 0)
}

function wireFileControls(): void {
  const machine = qs<HTMLSelectElement>("[data-role=file-machine]")
  const path = qs<HTMLInputElement>("[data-role=file-path]")
  machine?.addEventListener("change", () => { fileMachine = machine.value; filePath = "."; selectedFile = ""; void refreshFiles() })
  path?.addEventListener("keydown", (event) => { if (event.key === "Enter") { filePath = path.value || "."; selectedFile = ""; void refreshFiles() } })
  root.querySelectorAll<HTMLButtonElement>("[data-file]").forEach((row) => {
    row.addEventListener("click", () => void selectFile(row.dataset.file || ""))
    row.addEventListener("dblclick", () => {
      const entry = fileEntries.find((item) => item.path === row.dataset.file)
      if (entry?.type === "dir") { filePath = entry.path; selectedFile = ""; void refreshFiles() }
    })
  })
}

async function selectFile(path: string): Promise<void> {
  selectedFile = path
  fileEditing = false
  filePreview = null
  renderFiles()
  const requestMachine = fileMachine
  const entry = fileEntries.find((item) => item.path === path)
  if (!entry) return
  const preview = entry.type === "dir"
    ? { kind: "directory" }
    : await api<JsonRecord>(`/api/ui/files/preview?machine=${encodeURIComponent(requestMachine)}&path=${encodeURIComponent(path)}&columns=120&rows=50`)
  if (selectedFile !== path || fileMachine !== requestMachine) return
  filePreview = preview
  if (activeTab === "files") renderFiles()
}

async function refreshFiles(): Promise<void> {
  const requestMachine = fileMachine
  const requestPath = filePath
  const payload = await api<{ entries: FileEntry[]; path: string; machine: string }>(`/api/ui/files?machine=${encodeURIComponent(requestMachine)}&path=${encodeURIComponent(requestPath)}`)
  if (fileMachine !== requestMachine || filePath !== requestPath) return
  fileEntries = payload.entries || []
  filePath = payload.path || filePath
  if (!fileEntries.some((item) => item.path === selectedFile)) selectedFile = ""
  filePreview = null
  fileEditing = false
  if (activeTab === "files") renderFiles()
}

async function createFile(directory: boolean): Promise<void> {
  const name = await promptValue(directory ? "New folder" : "New file", "Name", "", `Create inside ${filePath}.`)
  if (!name?.trim()) return
  const requestMachine = fileMachine
  const requestParent = filePath
  const path = joinPath(requestParent, name.trim())
  await api(`/api/ui/files/${directory ? "mkdir" : "touch"}`, { method: "POST", body: JSON.stringify({ machine: requestMachine, path }) })
  if (fileMachine !== requestMachine || filePath !== requestParent) return
  selectedFile = path
  await refreshFiles()
}

async function deleteSelectedFile(): Promise<void> {
  if (!selectedFile) return
  const requestMachine = fileMachine
  const requestPath = selectedFile
  const entry = fileEntries.find((item) => item.path === requestPath)
  const confirmation = await promptValue("Delete entry", `Type ${basename(requestPath)} to confirm`, "", "This action cannot be undone by the Live Workspace.")
  if (confirmation !== basename(requestPath)) return
  await api("/api/ui/files/delete", { method: "POST", body: JSON.stringify({ machine: requestMachine, path: requestPath, recursive: entry?.type === "dir" }) })
  if (fileMachine !== requestMachine || selectedFile !== requestPath) return
  selectedFile = ""
  await refreshFiles()
}

async function beginFileEdit(): Promise<void> {
  if (!selectedFile) return
  const requestMachine = fileMachine
  const requestPath = selectedFile
  const content = await api<JsonRecord>(`/api/ui/files/content?machine=${encodeURIComponent(requestMachine)}&path=${encodeURIComponent(requestPath)}`)
  if (fileMachine !== requestMachine || selectedFile !== requestPath) return
  fileEditContent = String(content.content || "")
  fileEditSha = String(content.sha256 || "")
  fileEditing = true
  renderFiles()
}

async function saveFileEdit(): Promise<void> {
  if (!selectedFile) return
  const editor = qs<HTMLTextAreaElement>("[data-role=file-editor]")
  if (!editor) return
  const requestMachine = fileMachine
  const requestPath = selectedFile
  const requestSha = fileEditSha
  await api("/api/ui/files/write", { method: "POST", body: JSON.stringify({ machine: requestMachine, path: requestPath, content: editor.value, overwrite: true, expected_sha256: requestSha || null }) })
  if (fileMachine !== requestMachine || selectedFile !== requestPath) return
  fileEditing = false
  filePreview = null
  await selectFile(requestPath)
  notify("File saved", "success")
}

async function shareSelectedFile(ask: boolean): Promise<void> {
  if (!selectedFile) return
  const requestMachine = fileMachine
  const requestPath = selectedFile
  const content = await api<JsonRecord>(`/api/ui/files/content?machine=${encodeURIComponent(requestMachine)}&path=${encodeURIComponent(requestPath)}`)
  if (fileMachine !== requestMachine || selectedFile !== requestPath) return
  const text = truncateContext(String(content.content || ""))
  await updateHostModelContext({ content: [{ type: "text", text: `Selected file ${requestMachine}:${requestPath}:\n\n${text}` }], structuredContent: { selectedFile: { machine: requestMachine, path: requestPath, sha256: content.sha256 } } })
  notify("Selected file added to model context", "success")
  if (ask) await sendHostMessage({ role: "user", content: [{ type: "text", text: `Inspect the selected file ${requestPath} in Live Workspace. Explain anything important and suggest or make the next appropriate change.` }] })
}

function renderDiff(): void {
  const status = gitSnapshot ? String(gitSnapshot.status.stdout || gitSnapshot.status.stderr || "") : ""
  const diff = gitSnapshot ? String(gitSnapshot.diff.stdout || gitSnapshot.diff.stderr || "") : ""
  mainNode().innerHTML = `
    <section class="view diff-view"><div class="view-toolbar"><div><h2>Working tree diff</h2><p>${escapeHtml(gitSnapshot?.machine || diffMachine)}:${escapeHtml(gitSnapshot?.cwd || diffCwd)} · unstaged and staged changes</p></div><div class="toolbar-actions">${isDshHost ? "" : '<button class="button" data-action="diff-context">Send context</button>'}<button class="button" data-action="diff-ask">${icon("chat")}Ask for review</button><button class="button" data-action="refresh">${icon("refresh")}Refresh</button></div></div>
      <div class="diff-layout"><section class="panel status-panel"><div class="panel-head"><strong>Git status</strong><span>${escapeHtml(gitSnapshot?.cwd || diffCwd)}</span></div><pre>${escapeHtml(status || "Clean")}</pre></section><section class="panel diff-panel"><div class="panel-head"><strong>Changes</strong><span>${diff ? `${diff.split("\n").length} lines` : "clean"}</span></div><div class="diff-code">${gitSnapshot ? renderDiffHtml(diff) : '<div class="loading small"><span></span>Loading diff…</div>'}</div></section></div>
    </section>`
}

async function refreshDiff(): Promise<void> {
  if (!config) return
  const requestLiveId = config.liveId
  const requestMachine = diffMachine
  const requestCwd = diffCwd
  const snapshot = await api<{ machine?: string; cwd: string; status: JsonRecord; diff: JsonRecord }>(`/api/live/git?machine=${encodeURIComponent(requestMachine)}&cwd=${encodeURIComponent(requestCwd)}`)
  if (!config || config.liveId !== requestLiveId || diffMachine !== requestMachine || diffCwd !== requestCwd) return
  gitSnapshot = snapshot
  if (activeTab === "diff") renderDiff()
}

async function shareDiff(ask: boolean): Promise<void> {
  if (!gitSnapshot) await refreshDiff()
  const status = String(gitSnapshot?.status.stdout || "")
  const diff = truncateContext(String(gitSnapshot?.diff.stdout || ""), 28_000)
  await updateHostModelContext({ content: [{ type: "text", text: `Live Workspace git status (${gitSnapshot?.machine || diffMachine}):\n${status}\n\nDiff:\n${diff}` }], structuredContent: { git: { machine: gitSnapshot?.machine || diffMachine, cwd: gitSnapshot?.cwd || diffCwd, status } } })
  notify("Diff added to model context", "success")
  if (ask) await sendHostMessage({ role: "user", content: [{ type: "text", text: "Review the current Live Workspace git diff. Identify correctness risks, regressions, missing tests, and concrete improvements. Make fixes when appropriate." }] })
}

function renderJobs(): void {
  const jobs = dashboard?.jobs || []
  const sessions = dashboard?.sessions || []
  mainNode().innerHTML = `
    <section class="view jobs-view"><div class="view-toolbar"><div><h2>Jobs & sessions</h2><p>Active managed work and persistent shells across the workspace.</p></div><button class="button" data-action="refresh">${icon("refresh")}Refresh</button></div>
      <div class="jobs-grid"><section class="panel"><div class="panel-head"><strong>Managed jobs</strong><span>${jobs.length} active</span></div><div class="object-list">${jobs.length ? jobs.map(jobRow).join("") : '<div class="empty-state">No active managed jobs.</div>'}</div></section><section class="panel"><div class="panel-head"><strong>Standalone terminals</strong><span>${sessions.length} visible</span></div><div class="object-list">${sessions.length ? sessions.map(sessionRow).join("") : '<div class="empty-state">No standalone persistent terminals.</div>'}</div></section></div>
    </section>`
}

function jobRow(job: JsonRecord): string {
  const status = String(job.status || "unknown")
  const sessionId = String(job.session_id || "")
  const body = `<span class="state-dot ${escapeHtml(status)}"></span><div><strong>${escapeHtml(String(job.name || job.job_id || "job"))}</strong><p>${escapeHtml(String(job.command || job.kind || ""))}</p></div><div class="object-meta"><span>${escapeHtml(status)}</span><small>${sessionId ? "view output" : escapeHtml(String(job.machine || "local"))}</small></div>`
  return sessionId
    ? `<button class="object-row clickable" data-open-session="${escapeHtml(sessionId)}" data-machine="${escapeHtml(String(job.machine || "local"))}">${body}</button>`
    : `<div class="object-row">${body}</div>`
}

function sessionRow(session: JsonRecord): string {
  return `<button class="object-row clickable" data-open-session="${escapeHtml(String(session.session_id || ""))}"><span class="state-dot running"></span><div><strong>${escapeHtml(String(session.name || session.session_id || "terminal"))}</strong><p>${escapeHtml(String(session.backend || "persistent shell"))}</p></div><div class="object-meta"><span>${escapeHtml(String(session.machine || "local"))}</span><small>terminal</small></div></button>`
}

function wireJobRows(): void {
  root.querySelectorAll<HTMLButtonElement>("[data-open-session]").forEach((row) => {
    row.addEventListener("click", () => {
      selectedSession = row.dataset.openSession || ""
      const source = [...(dashboard?.jobs || []), ...(dashboard?.sessions || [])].find((item) => item.session_id === selectedSession)
      terminalMachine = row.dataset.machine || String(source?.machine || workloadMachine || "local")
      void switchTab("terminal")
    })
  })
}

function trackActivityDiscoveries(next: Dashboard): void {
  const jobs = next.jobs || []
  const sessions = next.sessions || []
  const nextJobs = new Set(jobs.map((job) => `${String(job.machine || "local")}:${String(job.job_id || job.session_id || job.name || "job")}`))
  const nextSessions = new Set(sessions.map((session) => `${String(session.machine || "local")}:${String(session.session_id || session.name || "terminal")}`))
  if (!activityDiscoveryInitialized) {
    knownActiveJobs = nextJobs
    knownStandaloneSessions = nextSessions
    activityDiscoveryInitialized = true
    return
  }
  for (const job of jobs) {
    const key = `${String(job.machine || "local")}:${String(job.job_id || job.session_id || job.name || "job")}`
    if (!knownActiveJobs.has(key)) notify(`Background job started: ${String(job.name || job.job_id || "job")}`, "info")
  }
  for (const session of sessions) {
    const key = `${String(session.machine || "local")}:${String(session.session_id || session.name || "terminal")}`
    if (!knownStandaloneSessions.has(key)) notify(`Terminal ready: ${String(session.name || session.session_id || "terminal")}`, "info")
  }
  knownActiveJobs = nextJobs
  knownStandaloneSessions = nextSessions
}

function renderRemotes(): void {
  const enabled = bootstrap ? Boolean((bootstrap.features as JsonRecord | undefined)?.remote) : true
  const rows = (remoteSnapshot?.machines as Machine[] | undefined) || []
  mainNode().innerHTML = `
    <section class="view remotes-view"><div class="view-toolbar"><div><h2>Remote machines</h2><p>Worker connectivity, workdirs and administrative actions.</p></div><div class="toolbar-actions"><button class="button primary" data-action="remote-invite" ${enabled ? "" : "disabled"}>Invite machine</button><button class="button" data-action="refresh">${icon("refresh")}Refresh</button></div></div>
      <div class="panel remote-panel"><div class="panel-head"><strong>Machines</strong><span>${enabled ? `${rows.length} registered` : "remote support disabled"}</span></div><div class="remote-grid">${rows.length ? rows.map(remoteCard).join("") : `<div class="empty-state">${enabled ? "No remote workers registered." : "Remote worker support is disabled."}</div>`}</div></div>
    </section>`
}

function remoteCard(machine: Machine): string {
  return `<article class="remote-card"><div class="remote-head"><span class="machine-icon">${icon("remotes")}</span><div><strong>${escapeHtml(machine.name)}</strong><span class="status-chip ${machine.status === "online" ? "online" : "offline"}">${escapeHtml(machine.status || "unknown")}</span></div></div><dl><div><dt>Workdir</dt><dd>${escapeHtml(machine.workdir || "—")}</dd></div><div><dt>Version</dt><dd>${escapeHtml(machine.version || "—")}</dd></div><div><dt>Platform</dt><dd>${escapeHtml(machine.platform || "—")}</dd></div></dl><footer><button class="text-button" data-action="remote-rename" data-machine="${escapeHtml(machine.name)}">Rename</button><button class="text-button danger" data-action="remote-revoke" data-machine="${escapeHtml(machine.name)}">Revoke</button></footer></article>`
}

async function refreshRemotes(): Promise<void> {
  if (bootstrap && !(bootstrap.features as JsonRecord | undefined)?.remote) { remoteSnapshot = { machines: [] }; if (activeTab === "remotes") renderRemotes(); return }
  remoteSnapshot = await api<JsonRecord>("/api/ui/remotes")
  if (activeTab === "remotes") renderRemotes()
}

async function createRemoteInvite(): Promise<void> {
  const name = await promptValue("Invite remote machine", "Machine name (optional)", "", "A one-time join command will be generated.")
  if (name === null) return
  const result = await api<JsonRecord>("/api/ui/remotes", { method: "POST", body: JSON.stringify({ name: name || null }) })
  const command = String(result.command || result.join_command || result.invite || "")
  if (command) {
    await navigator.clipboard.writeText(command)
    notify("Invite command copied to clipboard", "success")
  } else notify("Remote invitation created", "success")
  await refreshRemotes()
}

function resetFileTarget(machine: string, path: string): void {
  fileMachine = machine
  filePath = path
  fileEntries = []
  selectedFile = ""
  filePreview = null
  fileEditing = false
  fileEditContent = ""
  fileEditSha = ""
}

function resetTerminalTarget(machine: string): void {
  terminalMachine = machine
  terminalSessions = []
  selectedSession = ""
  terminalSocket?.close()
  terminalSocket = null
}

function resetWorkspaceTarget(machine: string, cwd: string): void {
  workloadMachine = machine
  diffMachine = machine
  diffCwd = cwd
  gitSnapshot = null
  dashboard = null
  activityDiscoveryInitialized = false
  knownActiveJobs.clear()
  knownStandaloneSessions.clear()
  activityExpandedEventKey = ""
  activityAuditDetails.clear()
  resetFileTarget(machine, cwd)
  resetTerminalTarget(machine)
}

function replaceMachineSelection(machine: string, replacement: string, replacementCwd?: string): void {
  if (config?.machine === machine) {
    config = { ...config, machine: replacement, cwd: replacementCwd ?? config.cwd }
    gitSnapshot = null
    dashboard = null
  }
  if (fileMachine === machine) {
    resetFileTarget(replacement, replacementCwd ?? filePath)
  }
  if (terminalMachine === machine) {
    resetTerminalTarget(replacement)
  }
  if (workloadMachine === machine) workloadMachine = replacement
  if (diffMachine === machine) {
    diffMachine = replacement
    if (replacementCwd) diffCwd = replacementCwd
    gitSnapshot = null
  }
}

async function renameRemote(machine: string): Promise<void> {
  if (!machine) return
  const name = await promptValue("Rename remote", "New name", machine)
  if (!name?.trim() || name === machine) return
  const newName = name.trim()
  await api("/api/ui/remotes/rename", { method: "POST", body: JSON.stringify({ machine, new_name: newName }) })
  replaceMachineSelection(machine, newName)
  await refreshAllCore()
  await refreshRemotes()
}

async function revokeRemote(machine: string): Promise<void> {
  if (!machine) return
  const confirmation = await promptValue("Revoke remote", `Type ${machine} to confirm`, "", "The worker will need a new invitation to reconnect.")
  if (confirmation !== machine) return
  await api("/api/ui/remotes/revoke", { method: "POST", body: JSON.stringify({ machine }) })
  replaceMachineSelection(machine, "local", ".")
  await refreshAllCore()
  await refreshRemotes()
}

function renderAudit(): void {
  mainNode().innerHTML = `
    <section class="view audit-view"><div class="view-toolbar"><div><h2>Audit stream</h2><p>Structured MCP activity retained by local-shell-mcp.</p></div><button class="button" data-action="refresh">${icon("refresh")}Refresh</button></div>
      <div class="panel audit-panel"><div class="panel-head"><strong>Recent entries</strong><span>${auditEntries.length} loaded</span></div><div class="audit-table"><div class="audit-header"><span>Time</span><span>Operation</span><span>Node</span><span>Status</span><span></span></div>${auditEntries.length ? auditEntries.map(auditRow).join("") : '<div class="empty-state">No audit entries.</div>'}</div></div>
    </section>`
}

function auditRow(entry: JsonRecord): string {
  const ok = entry.ok
  const status = ok === false ? "failed" : String(entry.status || (ok === true ? "ok" : "recorded"))
  return `<div class="audit-row"><time>${escapeHtml(formatClock(Number(entry.ts || 0)))}</time><div><strong>${escapeHtml(String(entry.tool || entry.operation || entry.event || "event"))}</strong><small>${escapeHtml(String(entry.purpose || entry.command || ""))}</small></div><span>${escapeHtml(String(entry.node || entry.machine || "local"))}</span><span class="audit-status ${ok === false ? "danger" : ""}">${escapeHtml(status)}</span><button class="text-button" data-action="audit-ask" data-id="${escapeHtml(String(entry.id || ""))}">Ask</button></div>`
}

async function refreshAudit(): Promise<void> {
  const payload = await api<JsonRecord>("/api/ui/audit?limit=150&sort=desc")
  auditEntries = (payload.entries as JsonRecord[] | undefined) || []
  if (activeTab === "audit") renderAudit()
}

async function askAboutAudit(id: string): Promise<void> {
  const entry = auditEntries.find((item) => String(item.id || "") === id)
  if (!entry) return
  let detail: unknown = entry
  try { detail = await api(`/api/ui/audit/detail?id=${encodeURIComponent(id)}`) } catch { /* preview is enough */ }
  await updateHostModelContext({ content: [{ type: "text", text: `Selected local-shell-mcp audit entry:\n${truncateContext(JSON.stringify(detail, null, 2), 20_000)}` }], structuredContent: { auditEntryId: id } })
  await sendHostMessage({ role: "user", content: [{ type: "text", text: "Explain the selected Live Workspace audit entry, whether it indicates a problem, and what I should do next." }] })
}

async function refreshJobs(): Promise<void> {
  if (!config) return
  const requestLiveId = config.liveId
  const requestMachine = workloadMachine
  const result = await api<Dashboard>(`/api/ui/dashboard?machine=${encodeURIComponent(requestMachine)}`)
  if (!config || config.liveId !== requestLiveId || workloadMachine !== requestMachine) return
  trackActivityDiscoveries(result)
  dashboard = result
  updateChrome()
  if (activeTab === "jobs") { renderJobs(); wireJobRows() }
}

async function refreshAllCore(): Promise<void> {
  if (!config) return
  if (passiveRefreshing) {
    coreRefreshQueued = true
    return
  }
  passiveRefreshing = true
  const requestLiveId = config.liveId
  const requestApiBase = config.apiBase
  let selectionChanged = false
  try {
    const boot = await api<JsonRecord>("/api/ui/bootstrap")
    if (!config || config.liveId !== requestLiveId || config.apiBase !== requestApiBase) {
      coreRefreshQueued = true
      return
    }
    bootstrap = boot
    const nested = boot.machines as JsonRecord | undefined
    machines = (nested?.machines as Machine[] | undefined) || []
    const available = new Set(machines.map((item) => item.name))
    const fallback = available.has("local") ? "local" : machines[0]?.name || "local"
    if (!available.has(config.machine)) {
      const missing = config.machine
      replaceMachineSelection(missing, fallback, ".")
      selectionChanged = true
    }
    const preferred = available.has(config.machine) ? config.machine : fallback
    if (!available.has(fileMachine)) {
      resetFileTarget(preferred, config.machine === preferred ? config.cwd : ".")
      selectionChanged = true
    }
    if (!available.has(terminalMachine)) {
      resetTerminalTarget(preferred)
      selectionChanged = true
    }
    if (!available.has(workloadMachine)) {
      workloadMachine = preferred
      dashboard = null
      selectionChanged = true
    }
    if (!available.has(diffMachine)) {
      diffMachine = preferred
      diffCwd = config.machine === preferred ? config.cwd : "."
      gitSnapshot = null
      selectionChanged = true
    }
    if (selectionChanged) renderCurrentTab()
    const dashboardMachine = workloadMachine
    const dash = await api<Dashboard>(`/api/ui/dashboard?machine=${encodeURIComponent(dashboardMachine || "local")}`)
    if (!config || config.liveId !== requestLiveId || config.apiBase !== requestApiBase || workloadMachine !== dashboardMachine) {
      coreRefreshQueued = true
      return
    }
    trackActivityDiscoveries(dash)
    dashboard = dash
    lastPassiveRefresh = Date.now()
    updateChrome()
    if (activeTab === "activity") renderActivity()
  } finally {
    passiveRefreshing = false
    if (coreRefreshQueued) {
      coreRefreshQueued = false
      queueMicrotask(() => void refreshAllCore())
    }
  }
  if (selectionChanged) {
    if (activeTab === "files") await refreshFiles()
    else if (activeTab === "terminal") await refreshTerminals()
    else if (activeTab === "diff") await refreshDiff()
    else if (activeTab === "jobs") { renderJobs(); wireJobRows() }
  }
}

async function refreshCurrent(force: boolean): Promise<void> {
  if (!config) return
  if (force || Date.now() - lastPassiveRefresh > 4_000) await refreshAllCore()
  if (activeTab === "terminal") await refreshTerminals()
  else if (activeTab === "files") await refreshFiles()
  else if (activeTab === "diff") await refreshDiff()
  else if (activeTab === "jobs") await refreshJobs()
  else if (activeTab === "remotes") await refreshRemotes()
  else if (activeTab === "audit") await refreshAudit()
  else renderActivity()
}

async function api<T = JsonRecord>(path: string, init: RequestInit = {}): Promise<T> {
  if (!config) throw new Error("Live Workspace is not connected")
  const url = new URL(path, config.apiBase.endsWith("/") ? config.apiBase : `${config.apiBase}/`)
  const headers = new Headers(init.headers)
  headers.set("Authorization", `Bearer ${config.token}`)
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json")
  const response = await fetch(url, { ...init, headers, credentials: "omit", cache: "no-store" })
  let payload: JsonRecord
  try { payload = await response.json() as JsonRecord } catch { throw new LiveApiError(`Live API returned HTTP ${response.status}`, response.status) }
  if (!response.ok || payload.ok === false) throw new LiveApiError(String(payload.message || payload.detail || `HTTP ${response.status}`), response.status)
  return (payload.data ?? payload) as T
}

function mergeEvents(incoming: LiveEvent[]): void {
  if (!incoming.length) return
  const bySeq = new Map(events.map((event) => [event.seq, event]))
  for (const event of incoming) {
    bySeq.set(event.seq, event)
    if (event.type === "tool.completed" || event.type === "tool.failed") {
      const callId = String(event.data.call_id || "")
      if (callId) {
        activityAuditDetails.delete(callId)
        activityDetailRevision += 1
      }
    }
  }
  events = [...bySeq.values()].sort((a, b) => a.seq - b.seq).slice(-800)
  cursor = Math.max(cursor, ...incoming.map((event) => event.seq))
  updateChrome()
  if (activeTab === "activity") renderActivity()
}

function resetActivityForSessionBoundary(): void {
  events = []
  activityExpandedEventKey = ""
  activityAuditDetails.clear()
  activityDetailRevision += 1
}

function applyLogicalSessionId(value: string | null | undefined): boolean {
  const nextSessionId = String(value ?? "")
  const changed = Boolean(config && config.sessionId !== nextSessionId)
  if (changed) {
    continuationClaimId = ""
    resetActivityForSessionBoundary()
  }
  if (config) config.sessionId = nextSessionId
  return changed
}

async function loadSnapshot(generation: number): Promise<boolean> {
  const payload = await api<{ channel: JsonRecord & { plan?: PlanState | null; session?: LogicalSessionState | null; session_id?: string | null }; events: LiveEvent[] }>("/api/live/snapshot")
  if (generation !== pollGeneration) return false
  applyLogicalSessionId(payload.channel.session_id)
  plan = payload.channel.plan || null
  logicalSession = payload.channel.session || null
  activityAuditDetails.clear()
  activityDetailRevision += 1
  events = payload.events || []
  cursor = Number(payload.channel.seq || events.at(-1)?.seq || 0)
  connected = true
  connectionMessage = "Live"
  updateChrome()
  renderCurrentTab()
  return true
}

async function pollEvents(generation: number): Promise<void> {
  while (!shuttingDown && config && generation === pollGeneration) {
    const payload = await api<{ events: LiveEvent[]; cursor: number; plan?: PlanState | null; session?: LogicalSessionState | null; session_id?: string | null }>(`/api/live/events?after=${cursor}&timeout=25`)
    if (generation !== pollGeneration) return
    const nextPlan = payload.plan || null
    observeContinuationPlan(nextPlan)
    applyLogicalSessionId(payload.session_id)
    plan = nextPlan
    logicalSession = payload.session || null
    mergeEvents(payload.events || [])
    cursor = Math.max(cursor, Number(payload.cursor || 0))
    connected = true
    connectionMessage = "Live"
    updateChrome()
    if (payload.events?.some((event) => ["tool.completed", "tool.failed", "human.action"].includes(event.type)) && Date.now() - lastPassiveRefresh > 1500) void refreshAllCore()
  }
}

async function checkPlanContinuation(): Promise<void> {
  if (!config || continuationChecking) return
  continuationChecking = true
  try {
    const requestedClaimId = continuationClaimId || `c_${crypto.randomUUID().replaceAll("-", "")}`
    continuationClaimId = requestedClaimId
    const claim = await api<{ claimed: boolean; claim_id?: string | null; plan?: PlanState | null; recent_events?: LiveEvent[]; continuation_count?: number; session_id?: string | null }>("/api/live/plan/continuation", {
      method: "POST",
      body: JSON.stringify({ action: "claim", claim_id: requestedClaimId }),
    })
    plan = claim.plan || plan
    if (!claim.claimed || !plan) {
      continuationClaimId = ""
      if (activeTab === "activity") renderActivity()
      return
    }

    const recent = claim.recent_events || []
    const sessionId = String(claim.session_id || config.sessionId || "")
    if (sessionId) config.sessionId = sessionId
    const attempt = Number(claim.continuation_count || plan.continuation_count + 1)
    const claimId = String(claim.claim_id || requestedClaimId)
    if (!claimId) throw new Error("Continuation claim did not include an identifier")
    continuationClaimId = claimId
    const checkpoint = {
      sessionId,
      objective: plan.objective,
      status: plan.status,
      steps: plan.steps,
      continuation: `${attempt}/${plan.max_continuations}`,
      recentActivity: recent,
    }
    let accepted = false
    let error = ""
    let validated = false
    try {
      await updateHostModelContext({
        content: [{ type: "text", text: `Active local-shell-mcp Goal checkpoint:\n${truncateContext(JSON.stringify(checkpoint, null, 2), 20_000)}` }],
        structuredContent: { localShellMcpSessionId: sessionId, localShellMcpPlan: plan, localShellMcpRecentActivity: recent },
      })
      const validation = await api<{ valid: boolean; plan?: PlanState | null }>("/api/live/plan/continuation", {
        method: "POST",
        body: JSON.stringify({ action: "validate", claim_id: claimId }),
      })
      plan = validation.plan || plan
      if (!validation.valid) {
        continuationClaimId = ""
        if (activeTab === "activity") renderActivity()
        return
      }
      validated = true
      const dispatch: ContinuationDispatch = {
        claimId,
        validatedAgentActivity: Number(plan.last_agent_activity),
        controller: new AbortController(),
        invalidationReason: "",
      }
      continuationDispatch = dispatch
      const dispatchWatcher = watchContinuationDispatch(dispatch)
      const resumeInstruction = !isDshHost && sessionId
        ? `First call session_manage(action="resume", session_id="${sessionId}", takeover=true) so this agent run inherits the durable task context. `
        : ""
      try {
        const response = await sendHostMessage({
          role: "user",
          content: [{ type: "text", text: `${resumeInstruction}Continue working on the active plan from its current state. Do not repeat completed steps. Keep working autonomously and keep the Session progress and Plan synchronized with execution: report meaningful checkpoints with session_manage(action="report", ...); use plan_manage(action="update") whenever step status or the execution plan changes; when every step is completed or skipped, call plan_manage(action="finish") before ending the turn; if you genuinely cannot continue without user input or an external condition, call plan_manage(action="block", note=...) and report the blocker before ending the turn.` }],
        }, { signal: dispatch.controller.signal })
        const result = response as unknown as JsonRecord
        accepted = result?.isError !== true
        if (!accepted) error = String(result?.message || "Host rejected the continuation message")
      } finally {
        if (dispatch.invalidationReason) error = dispatch.invalidationReason
        if (continuationDispatch === dispatch) continuationDispatch = null
        dispatch.controller.abort()
        await dispatchWatcher
      }
    } catch (sendError) {
      error = error || (sendError instanceof Error ? sendError.message : String(sendError))
    }

    try {
      const report = await api<{ plan: PlanState }>("/api/live/plan/continuation", {
        method: "POST",
        body: JSON.stringify({ action: "report", claim_id: claimId, accepted, error: error || null }),
      })
      plan = report.plan
      continuationClaimId = ""
    } catch (reportError) {
      if (validated) continuationClaimId = ""
      console.warn("Unable to report plan continuation result", reportError)
    }
    if (accepted) notify(`Goal continuation ${plan?.continuation_count || attempt}/${plan?.max_continuations || ""} sent`, "success")
    else if (error) console.warn("Goal continuation was not accepted", error)
    if (activeTab === "activity") renderActivity()
  } catch (error) {
    console.warn("Goal continuation check failed", error)
  } finally {
    continuationChecking = false
  }
}

async function runConnectionLoop(generation: number): Promise<void> {
  let attempt = 0
  let announcedRetry = false
  while (!shuttingDown && config && generation === pollGeneration) {
    try {
      connectionMessage = attempt ? "Reconnecting" : "Connecting"
      updateChrome()
      renderCurrentTab()
      if (!await loadSnapshot(generation)) return
      await refreshAllCore()
      if (generation !== pollGeneration) return
      await refreshCurrent(false)
      if (generation !== pollGeneration) return
      attempt = 0
      announcedRetry = false
      void checkPlanContinuation()
      await pollEvents(generation)
      return
    } catch (caught) {
      if (shuttingDown || !config || generation !== pollGeneration) return
      let error = caught
      if (isLiveCredentialError(error)) {
        const stale = config
        try {
          await refreshLiveCredentials({
            machine: stale.machine,
            cwd: stale.cwd,
            live_id: stale.liveId,
            ...(stale.sessionId ? { session_id: stale.sessionId } : {}),
          }, true)
          return
        } catch (credentialError) {
          error = credentialError
        }
      }
      connected = false
      connectionMessage = "Reconnecting"
      updateChrome()
      renderCurrentTab()
      if (!announcedRetry) {
        announcedRetry = true
        notify(`Connection lost; retrying automatically (${error instanceof Error ? error.message : String(error)})`, "warning")
      }
      const delay = reconnectDelayMs(attempt)
      attempt += 1
      await waitForRetry(delay)
    }
  }
}

function activateLiveConfig(nextConfig: LiveConfig): void {
  if (shuttingDown) return
  if (
    config
    && config.token === nextConfig.token
    && config.apiBase === nextConfig.apiBase
    && config.liveId === nextConfig.liveId
    && config.sessionId === nextConfig.sessionId
    && config.machine === nextConfig.machine
    && config.cwd === nextConfig.cwd
  ) return
  const channelChanged = !config || config.liveId !== nextConfig.liveId
  const sessionChanged = !config || config.sessionId !== nextConfig.sessionId
  const targetChanged = !config || config.machine !== nextConfig.machine || config.cwd !== nextConfig.cwd
  if (sessionChanged) continuationClaimId = ""
  if (channelChanged || sessionChanged) {
    resetActivityForSessionBoundary()
    if (channelChanged) cursor = 0
    connected = false
    plan = null
    logicalSession = null
  }
  if (targetChanged) resetWorkspaceTarget(nextConfig.machine, nextConfig.cwd)
  config = nextConfig
  pollGeneration += 1
  const generation = pollGeneration
  connectionMessage = "Connecting"
  renderCurrentTab()
  void runConnectionLoop(generation)
}

const credentialRefreshes = new Map<string, Promise<void>>()

async function requestDshLiveConfig(structured: JsonRecord, allowCreate: boolean): Promise<LiveConfig> {
  if (!dshBootstrap) throw new Error("DSH Live Workspace bridge is unavailable")
  const machine = String(structured.machine || "local")
  const cwd = String(structured.cwd || ".")
  const liveId = String(structured.live_id || "")
  const sessionId = String(structured.session_id || config?.sessionId || "")
  const invoke = async (id: string): Promise<LiveConfig> => {
    const url = new URL(dshBootstrap.configEndpoint, window.location.origin)
    url.searchParams.set("session", dshBootstrap.sessionId)
    url.searchParams.set("machine", machine)
    url.searchParams.set("cwd", cwd)
    if (id) url.searchParams.set("live_id", id)
    if (sessionId) url.searchParams.set("session_id", sessionId)
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store" })
    const payload = await response.json() as { ok?: boolean; data?: JsonRecord; message?: string }
    if (!response.ok || payload.ok === false || !payload.data) {
      throw new Error(String(payload.message || `DSH Live Workspace bridge returned HTTP ${response.status}`))
    }
    const data = payload.data
    const resolved: LiveConfig = {
      token: String(data.token || ""),
      apiBase: String(data.apiBase || ""),
      uiPath: String(data.uiPath || "/ui"),
      liveId: String(data.liveId || ""),
      sessionId: String(data.sessionId || ""),
      machine: String(data.machine || machine),
      cwd: String(data.cwd || cwd),
    }
    if (!resolved.token || !resolved.apiBase) {
      throw new Error("DSH omitted Live Workspace credentials")
    }
    return resolved
  }
  try {
    return await invoke(liveId)
  } catch (error) {
    if (!allowCreate || !liveId) throw error
    return await invoke("")
  }
}

async function requestLiveConfig(structured: JsonRecord, allowCreate: boolean): Promise<LiveConfig> {
  if (isDshHost) return await requestDshLiveConfig(structured, allowCreate)
  const machine = String(structured.machine || "local")
  const cwd = String(structured.cwd || ".")
  const liveId = String(structured.live_id || "")
  const sessionId = String(structured.session_id || config?.sessionId || "")
  const invoke = (id: string) => app.callServerTool({
    name: "live_workspace_reconnect",
    arguments: {
      machine,
      cwd,
      ...(id ? { live_id: id } : {}),
      ...(sessionId ? { session_id: sessionId } : {}),
    },
  })
  const response = await invoke(liveId)
  let resolvedResponse = response
  if (response.isError && allowCreate && liveId) {
    const message = response.content.find((item) => item.type === "text")
    const text = message?.type === "text" ? message.text : ""
    if (/different principal/i.test(text)) resolvedResponse = await invoke("")
  }
  if (resolvedResponse.isError) {
    const message = resolvedResponse.content.find((item) => item.type === "text")
    throw new Error(message?.type === "text" ? message.text : "Live Workspace authorization failed")
  }
  const responseStructured = (resolvedResponse.structuredContent || {}) as JsonRecord
  const hidden = resolvedResponse._meta?.["local-shell-mcp/live"] as JsonRecord | undefined
  const token = String(hidden?.token || "")
  const apiBase = String(hidden?.apiBase || responseStructured.api_base || structured.api_base || "")
  if (!token || !apiBase) {
    throw new Error("ChatGPT omitted Live Workspace credentials from the app-initiated tool result")
  }
  return {
    token,
    apiBase,
    uiPath: String(hidden?.uiPath || responseStructured.ui_path || structured.ui_path || "/ui"),
    liveId: String(hidden?.liveId || responseStructured.live_id || structured.live_id || ""),
    sessionId: String(responseStructured.session_id || structured.session_id || ""),
    machine: String(responseStructured.machine || machine),
    cwd: String(responseStructured.cwd || cwd),
  }
}

function refreshLiveCredentials(structured: JsonRecord, allowCreate = false): Promise<void> {
  const machine = String(structured.machine || "local")
  const cwd = String(structured.cwd || ".")
  const liveId = String(structured.live_id || "")
  const sessionId = String(structured.session_id || config?.sessionId || "")
  const key = `${liveId}\u0000${sessionId}\u0000${machine}\u0000${cwd}\u0000${allowCreate ? "create" : "reattach"}`
  const existing = credentialRefreshes.get(key)
  if (existing) return existing
  const refresh = (async () => {
    connectionMessage = "Authorizing Live Workspace…"
    renderCurrentTab()
    activateLiveConfig(await requestLiveConfig(structured, allowCreate))
  })().finally(() => {
    credentialRefreshes.delete(key)
  })
  credentialRefreshes.set(key, refresh)
  return refresh
}

async function recoverCredentialsForever(structured: JsonRecord): Promise<void> {
  let attempt = 0
  const announcedLiveId = String(structured.live_id || "")
  const announcedMachine = String(structured.machine || config?.machine || "local")
  const announcedCwd = String(structured.cwd || config?.cwd || ".")
  const needsRefresh = () => !config
    || Boolean(announcedLiveId && config.liveId !== announcedLiveId)
    || config.machine !== announcedMachine
    || config.cwd !== announcedCwd
  while (!shuttingDown && needsRefresh()) {
    try {
      await refreshLiveCredentials(structured, true)
      return
    } catch (error) {
      connected = false
      connectionMessage = "Reconnecting"
      updateChrome()
      renderCurrentTab()
      if (attempt === 0) notify(`Live authorization unavailable; retrying automatically (${error instanceof Error ? error.message : String(error)})`, "warning")
      const delay = reconnectDelayMs(attempt)
      attempt += 1
      await waitForRetry(delay)
    }
  }
}

async function configureFromToolResult(result: unknown): Promise<void> {
  if (shuttingDown) return
  const value = result as { _meta?: JsonRecord; structuredContent?: JsonRecord }
  const hidden = value?._meta?.["local-shell-mcp/live"] as JsonRecord | undefined
  const structured = value?.structuredContent || {}
  const token = String(hidden?.token || "")
  const apiBase = String(hidden?.apiBase || structured.api_base || "")
  if (!token || !apiBase) {
    const announcedLiveId = String(structured.live_id || "")
    const announcedMachine = String(structured.machine || config?.machine || "local")
    const announcedCwd = String(structured.cwd || config?.cwd || ".")
    if (
      config
      && (!announcedLiveId || announcedLiveId === config.liveId)
      && announcedMachine === config.machine
      && announcedCwd === config.cwd
    ) return
    await recoverCredentialsForever(structured)
    return
  }
  activateLiveConfig({
    token,
    apiBase,
    uiPath: String(hidden?.uiPath || structured.ui_path || "/ui"),
    liveId: String(hidden?.liveId || structured.live_id || ""),
    sessionId: String(structured.session_id || ""),
    machine: String(structured.machine || "local"),
    cwd: String(structured.cwd || "."),
  })
}

async function enterPreferredDisplayMode(): Promise<void> {
  if (isDshHost) {
    displayMode = "fullscreen"
    document.documentElement.dataset.displayMode = displayMode
    updateChrome()
    return
  }
  const context = app.getHostContext()
  const available = context?.availableDisplayModes || []
  if (available.includes("pip")) {
    if (context?.displayMode !== "pip") await requestDisplayMode("pip")
    return
  }
  if (available.includes("fullscreen")) {
    if (context?.displayMode !== "fullscreen") await requestDisplayMode("fullscreen")
    return
  }
  notify("Host does not support floating or fullscreen Live Workspace", "warning")
}

function applyHostContext(context: unknown): void {
  const value = (context || {}) as JsonRecord
  const theme = value.theme
  if (theme === "light" || theme === "dark") applyDocumentTheme(theme)
  const styles = value.styles as JsonRecord | undefined
  if (styles?.variables && typeof styles.variables === "object") applyHostStyleVariables(styles.variables as never)
  const css = styles?.css as JsonRecord | undefined
  if (typeof css?.fonts === "string") applyHostFonts(css.fonts)
  const mode = String(value.displayMode || "")
  if (mode === "fullscreen" || mode === "pip") displayMode = mode
  document.documentElement.dataset.displayMode = displayMode
  updateChrome()
}

type OpenAiGlobalsWindow = Window & {
  openai?: unknown
}

function configureFromOpenAiGlobals(globals?: unknown): boolean {
  if (shuttingDown) return false
  const result = toolResultFromOpenAiGlobals(globals ?? (window as OpenAiGlobalsWindow).openai)
  if (!result) return false
  void configureFromToolResult(result)
  return true
}

function onOpenAiGlobalsChanged(event: Event): void {
  if (shuttingDown) return
  const detail = (event as CustomEvent<{ globals?: unknown }>).detail
  configureFromOpenAiGlobals(detail?.globals)
}

let bridgeReady = false
let pendingToolResult: unknown = null
let initialToolResultResolve: ((result: unknown | null) => void) | null = null

function waitForInitialToolResult(timeoutMs: number): Promise<unknown | null> {
  if (pendingToolResult) {
    const result = pendingToolResult
    pendingToolResult = null
    return Promise.resolve(result)
  }
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      if (initialToolResultResolve === finish) initialToolResultResolve = null
      resolve(null)
    }, timeoutMs)
    const finish = (result: unknown | null) => {
      window.clearTimeout(timer)
      if (initialToolResultResolve === finish) initialToolResultResolve = null
      resolve(result)
    }
    initialToolResultResolve = finish
  })
}

app.ontoolresult = (result) => {
  if (shuttingDown) return
  if (initialToolResultResolve) {
    const resolve = initialToolResultResolve
    initialToolResultResolve = null
    resolve(result)
    return
  }
  if (!bridgeReady) {
    pendingToolResult = result
    return
  }
  void configureFromToolResult(result)
}
app.onhostcontextchanged = (context) => applyHostContext(context)

function stopLiveWorkspace(): void {
  if (shuttingDown) return
  shuttingDown = true
  abortContinuationDispatch("Live Workspace closed during continuation dispatch")
  pollGeneration += 1
  config = null
  connected = false
  destroyTerminal()
  window.removeEventListener("openai:set_globals", onOpenAiGlobalsChanged)
  window.removeEventListener("message", onDshPromptResult)
  for (const [requestId, waiter] of dshPromptWaiters) {
    dshPromptWaiters.delete(requestId)
    window.clearTimeout(waiter.timer)
    waiter.reject(new Error("Live Workspace closed before DSH accepted the message"))
  }
  if (passiveRefreshTimer !== null) {
    window.clearInterval(passiveRefreshTimer)
    passiveRefreshTimer = null
  }
  if (planContinuationTimer !== null) {
    window.clearInterval(planContinuationTimer)
    planContinuationTimer = null
  }
  if (countdownRenderTimer !== null) {
    window.clearInterval(countdownRenderTimer)
    countdownRenderTimer = null
  }
}

app.onteardown = async () => {
  stopLiveWorkspace()
  return {}
}

if (isDshHost) window.addEventListener("message", onDshPromptResult)
else window.addEventListener("openai:set_globals", onOpenAiGlobalsChanged)

shell()

void (async () => {
  try {
    if (isDshHost) {
      bridgeReady = true
      applyHostContext(currentHostContext())
      await enterPreferredDisplayMode()
      if (!shuttingDown) await recoverCredentialsForever({})
      return
    }
    await app.connect()
    if (shuttingDown) return
    bridgeReady = true
    applyHostContext(app.getHostContext())
    await enterPreferredDisplayMode()
    if (shuttingDown) return
    const initialResult = await waitForInitialToolResult(300)
    if (shuttingDown) return
    if (initialResult) await configureFromToolResult(initialResult)
    else if (!configureFromOpenAiGlobals()) await recoverCredentialsForever({})
  } catch (error) {
    connected = false
    connectionMessage = "Host bridge unavailable"
    updateChrome()
    renderCurrentTab()
    console.error("Unable to initialize MCP App bridge", error)
  }
})()

passiveRefreshTimer = window.setInterval(() => {
  if (!shuttingDown && config && Date.now() - lastPassiveRefresh > 6_000) void refreshAllCore()
}, 6_000)

planContinuationTimer = window.setInterval(() => {
  if (!shuttingDown && config) void checkPlanContinuation()
}, 30_000)

countdownRenderTimer = window.setInterval(() => {
  if (shuttingDown || !config || activeTab !== "activity") return
  refreshAutoContinueCard()
  const countdown = continuationCountdownState(plan)
  if (countdown.visible && countdown.remainingSeconds <= 0) void checkPlanContinuation()
}, 1_000)

window.addEventListener("beforeunload", () => {
  stopLiveWorkspace()
  if (!isDshHost) void app.close()
})
