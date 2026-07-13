import type {
  ApiEnvelope,
  AuditPayload,
  BootstrapPayload,
  FilePreview,
  FilesPayload,
  InvitePayload,
  MachinePayload,
  TerminalPayload,
  TodoItem,
  TodoPayload,
} from "./types"

const configuredBase = process.env.LOCAL_SHELL_MCP_UI_API_BASE || "http://127.0.0.1:8765/api/ui"
const localToken = process.env.LOCAL_SHELL_MCP_UI_LOCAL_TOKEN || ""
export const API_BASE = configuredBase.replace(/\/$/, "")

function queryString(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ""
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(localToken ? { "X-Local-Shell-MCP-UI-Token": localToken } : {}),
      ...init?.headers,
    },
  })
  let payload: ApiEnvelope<T>
  try {
    payload = (await response.json()) as ApiEnvelope<T>
  } catch {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message || payload.error || `${response.status} ${response.statusText}`)
  }
  return payload.data
}

export const api = {
  bootstrap(): Promise<BootstrapPayload> {
    return request("/bootstrap")
  },
  machines(): Promise<MachinePayload> {
    return request("/machines")
  },
  files(machine: string, path: string): Promise<FilesPayload> {
    return request(`/files${queryString({ machine, path })}`)
  },
  filePreview(machine: string, path: string): Promise<FilePreview> {
    return request(`/files/preview${queryString({ machine, path })}`)
  },
  fileContent(machine: string, path: string): Promise<FilePreview> {
    return request(`/files/content${queryString({ machine, path })}`)
  },
  fileAction<T = unknown>(action: string, body: Record<string, unknown>): Promise<T> {
    return request(`/files/${encodeURIComponent(action)}`, {
      method: "POST",
      body: JSON.stringify(body),
    })
  },
  terminals(machine: string): Promise<TerminalPayload> {
    return request(`/terminals${queryString({ machine })}`)
  },
  terminalRead(machine: string, sessionId: string, lines = 500): Promise<{ session_id: string; output: string }> {
    return request(`/terminals/read${queryString({ machine, session_id: sessionId, lines })}`)
  },
  terminalAction<T = unknown>(action: string, body: Record<string, unknown>): Promise<T> {
    return request(`/terminals/${encodeURIComponent(action)}`, {
      method: "POST",
      body: JSON.stringify(body),
    })
  },
  todos(): Promise<TodoPayload> {
    return request("/todos")
  },
  writeTodos(todos: TodoItem[], expectedRevision: number): Promise<TodoPayload> {
    return request("/todos", {
      method: "PUT",
      body: JSON.stringify({ todos, expected_revision: expectedRevision }),
    })
  },
  audit(filters: Record<string, string | number | boolean | null | undefined>): Promise<AuditPayload> {
    return request(`/audit${queryString(filters)}`)
  },
  remotes(): Promise<MachinePayload> {
    return request("/remotes")
  },
  invite(body: { name?: string; workdir?: string; ttl_s?: number }): Promise<InvitePayload> {
    return request("/remotes", {
      method: "POST",
      body: JSON.stringify(body),
    })
  },
  remoteAction<T = unknown>(action: string, body: Record<string, unknown>): Promise<T> {
    return request(`/remotes/${encodeURIComponent(action)}`, {
      method: "POST",
      body: JSON.stringify(body),
    })
  },
}

export function formatError(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
