export type ScreenName = "Files" | "Terminals" | "Todos" | "Audit" | "Remotes"

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
    yazi_available: boolean
  }
}

export interface ApiEnvelope<T> {
  ok: boolean
  message: string
  data: T
  error?: string
}
