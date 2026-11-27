export type DisplayMode = "fullscreen" | "pip"

export type LiveEvent = {
  seq: number
  ts: number
  type: string
  actor: string
  data: Record<string, unknown>
}

type JsonRecord = Record<string, unknown>

function jsonRecord(value: unknown): JsonRecord | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null
  return value as JsonRecord
}

export function toolResultFromOpenAiGlobals(globals: unknown): JsonRecord | null {
  const openai = jsonRecord(globals)
  if (!openai) return null

  const metadata = jsonRecord(openai.toolResponseMetadata)
  if (!metadata) return null

  const envelope = jsonRecord(metadata.mcp_tool_result) || jsonRecord(metadata.call_tool_result)
  if (!envelope) return null

  const structuredContent = jsonRecord(openai.toolOutput)
  if (structuredContent) return { ...envelope, structuredContent }

  return envelope
}

const LIVE_WORKSPACE_WIDGET_STATE_KEY = "localShellMcpLiveWorkspace"

export function liveWorkspaceResumeHintFromOpenAiGlobals(globals: unknown): JsonRecord | null {
  const openai = jsonRecord(globals)
  const widgetState = jsonRecord(openai?.widgetState)
  const stored = jsonRecord(widgetState?.[LIVE_WORKSPACE_WIDGET_STATE_KEY])
  if (!stored) return null

  const liveId = String(stored.live_id || "")
  const sessionId = String(stored.session_id || "")
  if (!liveId && !sessionId) return null

  return {
    ...(liveId ? { live_id: liveId } : {}),
    ...(sessionId ? { session_id: sessionId } : {}),
    machine: String(stored.machine || "local"),
    cwd: String(stored.cwd || "."),
  }
}

export function liveWorkspaceWidgetStateWithHint(
  globals: unknown,
  hint: { live_id: string; session_id?: string; machine: string; cwd: string },
): JsonRecord {
  const openai = jsonRecord(globals)
  const widgetState = jsonRecord(openai?.widgetState) || {}
  return {
    ...widgetState,
    [LIVE_WORKSPACE_WIDGET_STATE_KEY]: {
      live_id: hint.live_id,
      session_id: hint.session_id || "",
      machine: hint.machine,
      cwd: hint.cwd,
    },
  }
}

export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;")
}

export function formatClock(timestamp: number): string {
  if (!Number.isFinite(timestamp)) return "—"
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestamp * 1000))
}

export function formatDuration(milliseconds: unknown): string {
  const value = Number(milliseconds)
  if (!Number.isFinite(value) || value < 0) return ""
  if (value < 1000) return `${Math.round(value)} ms`
  if (value < 60_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`
  return `${Math.floor(value / 60_000)}m ${Math.round((value % 60_000) / 1000)}s`
}

export function formatBytes(bytes: unknown): string {
  const value = Number(bytes)
  if (!Number.isFinite(value) || value < 0) return "—"
  if (value < 1024) return `${value} B`
  const units = ["KiB", "MiB", "GiB", "TiB"]
  let size = value / 1024
  let unit = units[0]
  for (let index = 1; size >= 1024 && index < units.length; index += 1) {
    size /= 1024
    unit = units[index]
  }
  return `${size >= 10 ? size.toFixed(0) : size.toFixed(1)} ${unit}`
}

export function parentPath(path: string): string {
  if (!path || path === ".") return "."
  const driveRoot = path.match(/^([A-Za-z]:)([\\/]+)$/)
  if (driveRoot) return `${driveRoot[1]}${driveRoot[2][0]}`
  const uncShareRoot = /^(?:\\\\|\/\/)[^\\/]+[\\/][^\\/]+[\\/]?$/
  if (uncShareRoot.test(path)) return path
  const windows = path.includes("\\") && !path.includes("/")
  const separator = windows ? "\\" : "/"
  const normalized = path.replace(/[\\/]+$/, "")
  if (!normalized) return separator
  const index = Math.max(normalized.lastIndexOf("/"), normalized.lastIndexOf("\\"))
  if (index < 0) return "."
  if (index === 0) return separator
  if (index === 2 && normalized[1] === ":") return `${normalized.slice(0, 2)}${separator}`
  return normalized.slice(0, index)
}

export function basename(path: string): string {
  const normalized = path.replace(/[\\/]+$/, "")
  const index = Math.max(normalized.lastIndexOf("/"), normalized.lastIndexOf("\\"))
  return normalized.slice(index + 1) || normalized || "."
}

export function joinPath(parent: string, child: string): string {
  if (!parent || parent === ".") return child
  const separator = parent.includes("\\") && !parent.includes("/") ? "\\" : "/"
  if (parent === "/") return `/${child}`
  return `${parent.replace(/[\\/]+$/, "")}${separator}${child}`
}

export function toggleWorkspaceDisplayMode(current: DisplayMode): DisplayMode {
  return current === "fullscreen" ? "pip" : "fullscreen"
}

export function reconnectDelayMs(attempt: number): number {
  const exponent = Math.min(5, Math.max(0, Math.floor(attempt)))
  return Math.min(15_000, 500 * (2 ** exponent))
}

export type ReverseFeedScrollState = {
  followStart: boolean
  endGap: number
}

export function captureReverseFeedScrollState(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  followThreshold = 2,
): ReverseFeedScrollState {
  return {
    followStart: scrollTop <= followThreshold,
    endGap: Math.max(0, scrollHeight - clientHeight - scrollTop),
  }
}

export function restoreReverseFeedScrollTop(
  state: ReverseFeedScrollState,
  scrollHeight: number,
  clientHeight: number,
): number {
  if (state.followStart) return 0
  return Math.max(0, scrollHeight - clientHeight - state.endGap)
}

export type ContinuationCountdownState = {
  visible: boolean
  remainingSeconds: number
  idleSeconds: number
  progress: number
}

export function continuationCountdownState(
  plan: {
    status: string
    continuation_pending: boolean
    auto_continue_exhausted: boolean
    continuation_driver?: string
    in_flight_calls?: number
    last_agent_activity: number
    execution_lease_s: number
    continuation_due_at: number
    continuation_retry_after?: number | null
  } | null,
  nowSeconds = Date.now() / 1000,
  revealAfterSeconds = 5 * 60,
): ContinuationCountdownState {
  if (!plan || plan.status !== "active" || plan.continuation_driver === "chat" || plan.continuation_pending || plan.auto_continue_exhausted || Number(plan.in_flight_calls || 0) > 0) {
    return { visible: false, remainingSeconds: 0, idleSeconds: 0, progress: 0 }
  }
  const idleSeconds = Math.max(0, nowSeconds - Number(plan.last_agent_activity))
  const dueAt = Math.max(
    Number(plan.continuation_due_at),
    Number(plan.continuation_retry_after || 0),
  )
  const remainingSeconds = Math.max(0, dueAt - nowSeconds)
  const countdownWindow = Math.max(1, Number(plan.execution_lease_s || 0) - revealAfterSeconds)
  const elapsedInWindow = Math.max(0, idleSeconds - revealAfterSeconds)
  return {
    visible: idleSeconds >= revealAfterSeconds,
    remainingSeconds,
    idleSeconds,
    progress: Math.min(1, elapsedInWindow / countdownWindow),
  }
}

export function formatCountdown(seconds: number): string {
  const rounded = Math.max(0, Math.ceil(seconds))
  const minutes = Math.floor(rounded / 60)
  const remainder = rounded % 60
  return `${minutes}:${String(remainder).padStart(2, "0")}`
}

export function continuationDispatchStillValid(
  plan: {
    status: string
    continuation_pending: boolean
    continuation_claim_id?: string | null
    last_agent_activity: number
  } | null,
  claimId: string,
  validatedAgentActivity: number,
): boolean {
  return Boolean(
    plan
    && plan.status === "active"
    && plan.continuation_pending
    && plan.continuation_claim_id === claimId
    && Number(plan.last_agent_activity) <= validatedAgentActivity,
  )
}

const TOOL_TERMINAL_EVENTS = new Set(["tool.completed", "tool.failed", "tool.cancelled", "tool.blocked"])

function mergedActivityKey(event: LiveEvent): string | null {
  const callId = String(event.data.call_id || "")
  if (callId && (event.type === "tool.started" || TOOL_TERMINAL_EVENTS.has(event.type))) {
    return `${event.type}:${callId}`
  }
  return null
}

export function mergeActivityEvents(durable: LiveEvent[], live: LiveEvent[]): LiveEvent[] {
  const keyed = new Map<string, LiveEvent>()
  const unkeyed: LiveEvent[] = []

  for (const event of live) {
    const key = mergedActivityKey(event)
    if (key) keyed.set(key, event)
    else unkeyed.push(event)
  }
  // Prefer durable copies of agent tool lifecycle events because they survive
  // reconnects/restarts, while retaining human/live-only channel events.
  for (const event of durable) {
    const key = mergedActivityKey(event)
    if (key) keyed.set(key, event)
    else unkeyed.push(event)
  }

  return [...unkeyed, ...keyed.values()].sort((left, right) => {
    if (left.ts !== right.ts) return left.ts - right.ts
    return left.seq - right.seq
  })
}

export function coalesceActivityEvents(events: LiveEvent[]): LiveEvent[] {
  const rows: LiveEvent[] = []
  const pendingByCallId = new Map<string, number>()

  for (const event of events) {
    const callId = String(event.data.call_id || "")
    if (event.type === "tool.started") {
      rows.push(event)
      if (callId) pendingByCallId.set(callId, rows.length - 1)
      continue
    }

    if (callId && TOOL_TERMINAL_EVENTS.has(event.type)) {
      const pendingIndex = pendingByCallId.get(callId)
      if (pendingIndex !== undefined) {
        const started = rows[pendingIndex]
        rows[pendingIndex] = {
          ...event,
          ts: started.ts,
          data: {
            ...started.data,
            ...event.data,
            started_at: started.ts,
            finished_at: event.ts,
          },
        }
        pendingByCallId.delete(callId)
        continue
      }
    }

    // A rolling activity window may begin with a completion whose matching
    // start has already aged out. Keep that terminal event as a valid row.
    rows.push(event)
  }

  return rows
}

export function activityEventKey(event: LiveEvent): string {
  const callId = String(event.data.call_id || "")
  if (callId && (event.type === "tool.started" || TOOL_TERMINAL_EVENTS.has(event.type))) {
    return `call:${callId}`
  }
  return String(event.seq)
}

export function isOperationalActivityEvent(event: LiveEvent): boolean {
  if (event.type === "channel.opened" || event.type === "session.attached") return false
  if (event.type === "human.action" && event.data.action === "terminal.input") return false
  return !["workspace_open", "open_live_workspace", "live_workspace_reconnect"].includes(String(event.data.tool || ""))
}

export function activityIntent(event: LiveEvent): string {
  const tool = String(event.data.tool || "")
  const purpose = typeof event.data.purpose === "string" ? event.data.purpose.trim() : ""
  const path = typeof event.data.path === "string" ? event.data.path : ""
  const name = typeof event.data.name === "string" ? event.data.name : ""
  if (purpose) return purpose
  if (["run_shell", "run_shell_tool"].includes(tool)) return "Running command"
  if (tool === "shell_start") return name ? `Opening ${name}` : "Opening terminal"
  if (tool === "shell_send") return "Sending terminal input"
  if (tool === "shell_read") return "Reading terminal output"
  if (["shell_stop", "shell_kill"].includes(tool)) return "Closing terminal"
  if (tool === "job_start") return name ? `Starting ${name}` : "Starting background job"
  if (tool === "job_tail") return "Reading job output"
  if (tool === "job_stop") return "Stopping background job"
  if (tool === "job_retry") return "Retrying background job"
  if (tool === "remote_transfer") return "Transferring files"
  if (["file_read", "read_file"].includes(tool)) return path ? `Reading ${basename(path)}` : "Reading file"
  if (["file_write", "write_file"].includes(tool)) return path ? `Writing ${basename(path)}` : "Writing file"
  if (["file_edit", "edit_file"].includes(tool)) return path ? `Editing ${basename(path)}` : "Editing file"
  if (["file_delete", "delete_file_or_dir"].includes(tool)) return path ? `Deleting ${basename(path)}` : "Deleting file"
  if (["file_patch", "apply_patch"].includes(tool)) return "Applying patch"
  if (["file_grep", "file_glob", "file_tree", "file_list", "grep_search", "glob_search", "tree_view", "list_files", "search"].includes(tool)) return "Searching workspace"
  if (tool === "browser_session" || tool === "browser_act" || tool === "browser_snapshot" || tool === "browser_run_script") return "Using browser"
  if (tool === "remote_manage") return "Managing remote machines"
  if (tool === "audit_tail") return "Reading audit log"
  if (!tool) return eventTitle(event)
  return tool.replaceAll("_", " ")
}

export type ActivityDestination = "terminal" | "jobs" | "files" | "remotes" | "audit" | "detail" | null

export function activityDestination(event: LiveEvent): ActivityDestination {
  const tool = String(event.data.tool || "")
  if (["shell_start", "shell_send", "shell_read", "shell_stop", "shell_kill"].includes(tool)) {
    return event.data.session_id ? "terminal" : event.data.call_id ? "detail" : null
  }
  if (["job_start", "job_list", "job_tail", "job_stop", "job_retry", "remote_transfer"].includes(tool)) return "jobs"
  if (["file_read", "file_write", "file_edit", "file_delete", "file_list", "file_glob", "file_grep", "file_tree", "read_file", "write_file", "edit_file", "delete_file_or_dir", "list_files", "glob_search", "grep_search", "tree_view", "search"].includes(tool)) return "files"
  if (["file_patch", "apply_patch"].includes(tool)) return event.data.call_id ? "detail" : null
  if (tool === "remote_manage") return "remotes"
  if (tool === "audit_tail") return "audit"
  if (["run_shell", "run_python", "run_shell_tool", "run_python_tool"].includes(tool)) return "detail"
  return event.data.call_id ? "detail" : null
}

export function eventTitle(event: LiveEvent): string {
  const tool = String(event.data.tool ?? "")
  const action = String(event.data.action ?? "")
  if (event.type === "tool.started") return tool ? `Running ${tool}` : "Tool started"
  if (event.type === "tool.completed") return tool ? `${tool} completed` : "Tool completed"
  if (event.type === "tool.failed") return tool ? `${tool} failed` : "Tool failed"
  if (event.type === "tool.cancelled") return tool ? `${tool} cancelled` : "Tool cancelled"
  if (event.type === "tool.blocked") return tool ? `${tool} blocked` : "Tool blocked"
  if (event.type === "channel.opened") return "Live workspace connected"
  if (event.type === "human.inspected_diff") return "Human inspected diff"
  if (event.type === "human.action") return action ? `Human: ${action}` : "Human action"
  if (event.type === "session.started") return "Logical session started"
  if (event.type === "session.resumed") return "Logical session resumed"
  if (event.type === "session.reported") return "Progress checkpoint"
  if (event.type === "session.completed") return "Logical session completed"
  if (event.type === "session.cancelled") return "Logical session cancelled"
  if (event.type === "plan.started") return "Plan started"
  if (event.type === "plan.updated") return "Plan updated"
  if (event.type === "plan.blocked") return "Plan paused"
  if (event.type === "plan.resumed") return "Plan resumed"
  if (event.type === "plan.completed") return "Plan completed"
  if (event.type === "plan.cancelled") return "Plan cancelled"
  if (event.type === "plan.continuation_requested") return "Auto continuation requested"
  if (event.type === "plan.continuation_sent") return "Auto continuation sent"
  if (event.type === "plan.continuation_failed") return "Auto continuation failed"
  return event.type.replaceAll(".", " ")
}

export function eventDetail(event: LiveEvent): string {
  const data = event.data
  const pieces: string[] = []
  if (event.type.startsWith("plan.")) {
    if (typeof data.reason === "string" && data.reason) pieces.push(data.reason)
    const activeStep = data.active_step
    if (activeStep && typeof activeStep === "object" && !Array.isArray(activeStep)) {
      const text = (activeStep as Record<string, unknown>).text
      if (typeof text === "string" && text) pieces.push(`Active: ${text}`)
    }
    if (data.total_steps !== undefined) pieces.push(`${String(data.completed_steps || 0)}/${String(data.total_steps)} complete`)
    if (data.revision !== undefined) pieces.push(`r${String(data.revision)}`)
    if (pieces.length) return pieces.join(" · ")
  }
  for (const key of ["machine", "path", "cwd", "session_id", "job_id"] as const) {
    const value = data[key]
    if (value !== undefined && value !== null && value !== "") pieces.push(String(value))
  }
  if (typeof data.summary === "string" && data.summary) pieces.push(data.summary)
  if (typeof data.next === "string" && data.next) pieces.push(`Next: ${data.next}`)
  if (typeof data.objective === "string" && data.objective) pieces.push(data.objective)
  if (typeof data.reason === "string" && data.reason) pieces.push(data.reason)
  if (typeof data.command === "string" && data.command) pieces.push(data.command)
  if (typeof data.error === "string" && data.error) pieces.push(data.error)
  const duration = formatDuration(data.duration_ms)
  if (duration) pieces.push(duration)
  return pieces.join(" · ")
}

export function eventTone(event: LiveEvent): "success" | "danger" | "warning" | "info" | "muted" {
  if (event.type === "tool.failed") return "danger"
  if (event.type === "tool.cancelled") return "warning"
  if (event.type === "tool.blocked") return "warning"
  if (event.type === "tool.completed") return "success"
  if (event.type === "tool.started") return "info"
  if (event.type === "human.action") return "info"
  if (event.type === "session.completed" || event.type === "plan.completed" || event.type === "plan.continuation_sent") return "success"
  if (event.type === "session.cancelled" || event.type === "plan.cancelled" || event.type === "plan.continuation_failed") return "danger"
  if (event.type === "plan.blocked") return "warning"
  if (event.type.startsWith("session.") || event.type.startsWith("plan.")) return "info"
  return "muted"
}


export function truncateContext(value: string, maxChars = 24_000): string {
  if (value.length <= maxChars) return value
  return `${value.slice(0, maxChars)}\n… [truncated by Live Workspace]`
}
