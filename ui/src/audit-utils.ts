import type { AuditEntry } from "./types"

export const AUDIT_OPERATIONS = ["", "files", "shell", "jobs", "transfer", "browser", "remote", "agent"] as const

const AUDIT_LIST_MIN_WIDTH = 58
const AUDIT_LIST_MAX_WIDTH = 86
const AUDIT_DETAIL_MIN_WIDTH = 44

export interface AuditListLayout {
  paneWidth: number
  nodeWidth: number
  operationWidth: number
  toolWidth: number
}

export function auditStackedVisibleRows(
  screenHeight: number,
  detailHeight: number,
  hasFilterSummary: boolean,
): number {
  // Filters, key hints, gaps, and the list panel chrome consume 13 rows.
  return Math.max(1, screenHeight - detailHeight - 13 - (hasFilterSummary ? 3 : 0))
}

type JsonRecord = Record<string, unknown>

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function contentWidth(values: string[], minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, ...values.map((value) => value.length)))
}

export function auditListLayout(entries: AuditEntry[], screenWidth: number): AuditListLayout {
  const nodeWidth = contentWidth(entries.map((entry) => entry.node), 8, 24)
  const operationWidth = contentWidth(entries.map((entry) => entry.operation), 10, 16)
  const toolWidth = contentWidth(entries.map((entry) => entry.tool || entry.event), 18, 28)
  const desiredWidth = 18 + nodeWidth + operationWidth + toolWidth
  const availableWidth = Math.max(
    AUDIT_LIST_MIN_WIDTH,
    Math.min(AUDIT_LIST_MAX_WIDTH, screenWidth - AUDIT_DETAIL_MIN_WIDTH - 1),
  )

  return {
    paneWidth: Math.min(Math.max(AUDIT_LIST_MIN_WIDTH, desiredWidth), availableWidth),
    nodeWidth,
    operationWidth,
    toolWidth,
  }
}

export function fitAuditColumn(value: string, width: number): string {
  if (value.length <= width) return value.padEnd(width)
  if (width <= 1) return value.slice(0, width)
  return `${value.slice(0, width - 1)}…`
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
  let output: unknown
  if (entry.output !== undefined) output = entry.output
  else if (entry.result !== undefined) output = entry.result
  else {
    const fallback: JsonRecord = {}
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
      if (entry[key] !== undefined) fallback[key] = entry[key]
    }
    output = cleanAuditValue(fallback)
  }
  const related = cleanAuditValue(entry.related_events)
  if (related === undefined) return output
  return cleanAuditValue({ result: unwrapToolEnvelope(output), related_events: related })
}
