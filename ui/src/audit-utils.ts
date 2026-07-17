import type { AuditEntry } from "./types"

export const AUDIT_OPERATIONS = ["", "files", "shell", "jobs", "transfer", "browser", "remote", "agent"] as const

type JsonRecord = Record<string, unknown>

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function auditEntryKey(entry: AuditEntry): string {
  if (entry.id) return entry.id
  if (entry.call_id) return `call:${entry.call_id}`
  return [entry.event, entry.tool || "", entry.ts, entry.node, entry.session || ""].join("|")
}

export function selectionAfterRefresh(
  previousEntries: AuditEntry[],
  previousSelected: number,
  nextEntries: AuditEntry[],
): number {
  if (nextEntries.length === 0 || previousSelected <= 0) return 0
  const previous = previousEntries[previousSelected]
  if (!previous) return Math.min(previousSelected, nextEntries.length - 1)
  const key = auditEntryKey(previous)
  const preserved = nextEntries.findIndex((entry) => auditEntryKey(entry) === key)
  return preserved >= 0 ? preserved : Math.min(previousSelected, nextEntries.length - 1)
}

function cleanAuditValue(value: unknown): unknown {
  if (value === null || value === undefined || value === "") return undefined
  if (Array.isArray(value)) {
    const items = value.map(cleanAuditValue).filter((item) => item !== undefined)
    return items.length ? items : undefined
  }
  if (isRecord(value)) {
    const entries = Object.entries(value)
      .map(([key, item]) => [key, cleanAuditValue(item)] as const)
      .filter(([, item]) => item !== undefined)
    return entries.length ? Object.fromEntries(entries) : undefined
  }
  return value
}

function parseJsonString(value: string): unknown {
  const trimmed = value.trim()
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return value
  try {
    return JSON.parse(trimmed)
  } catch {
    return value
  }
}

function unwrapToolEnvelope(value: unknown): unknown {
  if (!isRecord(value) || !("data" in value)) return value
  const allowed = new Set(["ok", "message", "data", "error", "error_type"])
  if (Object.keys(value).some((key) => !allowed.has(key))) return value

  const data = cleanAuditValue(value.data)
  const message = cleanAuditValue(value.message)
  const error = cleanAuditValue(value.error)
  const errorType = cleanAuditValue(value.error_type)
  if (value.ok === false || error !== undefined || errorType !== undefined) {
    return cleanAuditValue({ message, error, error_type: errorType, data })
  }
  return data ?? message
}

export function formatAuditValue(value: unknown, emptyLabel: string): string {
  const parsed = typeof value === "string" ? parseJsonString(value) : value
  const cleaned = cleanAuditValue(unwrapToolEnvelope(parsed))
  if (cleaned === undefined) return emptyLabel
  if (typeof cleaned === "string") return cleaned
  return JSON.stringify(cleaned, null, 2)
}

export function auditInput(entry: AuditEntry): unknown {
  if (entry.input !== undefined) return entry.input
  if (isRecord(entry.arguments)) {
    return entry.arguments.keyword_args ?? entry.arguments
  }
  const input: JsonRecord = {}
  for (const key of ["command", "cwd", "path", "url", "session", "machine"]) {
    if (entry[key] !== undefined) input[key] = entry[key]
  }
  return cleanAuditValue(input)
}

export function auditOutput(entry: AuditEntry): unknown {
  if (entry.output !== undefined) return entry.output
  if (entry.result !== undefined) return entry.result
  const output: JsonRecord = {}
  for (const key of [
    "ok",
    "error",
    "error_type",
    "exit_code",
    "timed_out",
    "duration_ms",
    "stdout",
    "stderr",
    "truncated",
  ]) {
    if (entry[key] !== undefined) output[key] = entry[key]
  }
  return cleanAuditValue(output)
}
