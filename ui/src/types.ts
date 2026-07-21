export type ScreenName = "Dashboard" | "Files" | "Terminals" | "Remotes" | "Audit" | "Todos"

export interface Machine {
  name: string
  status: "online" | "offline" | string
  workdir?: string | null
  last_seen?: number | null
  last_seen_age_s?: number | null
  capabilities?: string[]
  info?: Record<string, unknown>
}

export interface MachinePayload {
  machines: Machine[]
  counts: Record<string, number>
  enabled?: boolean
}

export interface FileEntry {
  path: string
  name: string
  type: "dir" | "file" | "other" | string
  size?: number | null
  modified?: number | null
  hidden?: boolean
}

export interface FilesPayload {
  machine: string
  path: string
  parent: string
  entries: FileEntry[]
  parent_entries: FileEntry[]
}

export interface FilePreview {
  kind: "directory" | "text" | "binary" | "image"
  content?: string
  preview?: string
  rgba?: string
  mime_type?: string
  width?: number
  height?: number
  cell_width?: number
  cell_height?: number
  original_width?: number
  original_height?: number
  entries?: FileEntry[]
  size?: number
  bytes?: number
  path?: string
  truncated?: boolean
  sha256?: string | null
  [key: string]: unknown
}

export interface TerminalSession {
  session_id: string
  created?: string | number | null
  attached?: string | number | null
  backend?: string
}

export interface TerminalPayload {
  machine: string
  sessions: TerminalSession[]
}

export interface TodoItem {
  id: string
  content: string
  status: "pending" | "in_progress" | "completed" | string
  priority: "low" | "medium" | "high" | string
}

export interface TodoPayload {
  revision: number
  updated_at?: number | null
  todos: TodoItem[]
}

export interface AuditEntry {
  id?: string
  call_id?: string
  ts: number
  event: string
  node: string
  operation: string
  tool?: string
  session?: string
  command?: string
  cwd?: string
  ok?: boolean
  paired?: boolean
  status?: "success" | "failed" | "running" | "unpaired" | "completed" | string
  duration_ms?: number
  input?: unknown
  output?: unknown
  result?: unknown
  arguments?: unknown
  error?: string
  error_type?: string
  image_preview?: FilePreview
  image_preview_error?: string
  [key: string]: unknown
}

export interface AuditPayload {
  entries: AuditEntry[]
  count: number
  total_matched: number
}

export interface InvitePayload {
  code: string
  name?: string | null
  workdir?: string | null
  expires_at: number
  ttl_s: number
  join_url: string
  command: string
}

export interface BootstrapPayload {
  version: Record<string, unknown>
  machines: MachinePayload
  todos: TodoPayload
  features: {
    remote: boolean
    wallpaper: "bing" | "aurora" | "none" | string
  }
}

export interface DashboardSystem {
  timestamp: number
  cpu_percent?: number | null
  cpu_count?: number | null
  memory_percent?: number | null
  memory_used_bytes?: number | null
  memory_total_bytes?: number | null
  disk_percent?: number | null
  disk_used_bytes?: number | null
  disk_total_bytes?: number | null
  load_1m?: number | null
  network_rx_bps?: number | null
  network_tx_bps?: number | null
  uptime_s?: number | null
}

export interface DashboardJob {
  job_id?: string
  name?: string
  status?: string
  command?: string
  cwd?: string
  session_id?: string
  created_at?: number | null
  updated_at?: number | null
  last_started_at?: number | null
}

export interface DashboardAlert {
  severity: "critical" | "warning" | "info" | string
  title: string
  detail?: string
  node?: string
  age_s?: number | null
}

export interface DashboardActivity {
  timestamp?: number | null
  node: string
  kind: "success" | "failed" | "running" | string
  title: string
  detail?: string
}

export interface DashboardPayload {
  generated_at: number
  health: "healthy" | "attention" | "critical" | string
  version: Record<string, unknown>
  system: DashboardSystem
  machines: MachinePayload
  jobs: DashboardJob[]
  job_counts: Record<string, number>
  sessions: TerminalSession[]
  session_count: number
  alerts: DashboardAlert[]
  activity: DashboardActivity[]
  audit_total_24h: number
  todo_counts: { total: number; open: number }
}

export interface ApiEnvelope<T> {
  ok: boolean
  message: string
  data: T
  error?: string
}
