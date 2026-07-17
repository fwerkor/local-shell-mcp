import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, Modal, Panel, useVisibleRows } from "./components"
import { clampIndex } from "./state-utils"
import { theme } from "./theme"
import type { AuditEntry, Machine } from "./types"

type AuditDialog = { type: "none" } | { type: "search" } | { type: "event" } | { type: "session" }

const TIME_RANGES = [
  { label: "15m", seconds: 15 * 60 },
  { label: "1h", seconds: 60 * 60 },
  { label: "24h", seconds: 24 * 60 * 60 },
  { label: "7d", seconds: 7 * 24 * 60 * 60 },
  { label: "All", seconds: 0 },
]
const OPERATIONS = ["", "run", "read", "write", "shell", "git", "remote", "browser", "download", "auth"]

function entryColor(entry: AuditEntry): string {
  if (entry.ok === false || entry.error) return theme.red
  if (entry.ok === true) return theme.green
  if (entry.event.includes("start")) return theme.cyan
  return theme.muted
}

function detail(entry: AuditEntry): string {
  if (entry.command) return String(entry.command)
  if (entry.cwd) return String(entry.cwd)
  if (entry.error) return String(entry.error)
  const args = entry.arguments as Record<string, unknown> | undefined
  if (args) return JSON.stringify(args)
  return JSON.stringify(entry)
}

export function AuditScreen({
  machines,
  width,
  height,
  setStatus,
  keyboardEnabled,
  onInteractionLockChange,
}: {
  machines: Machine[]
  width: number
  height: number
  setStatus: (message: string) => void
  keyboardEnabled: boolean
  onInteractionLockChange: (locked: boolean) => void
}) {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [selected, setSelected] = useState(0)
  const [nodeIndex, setNodeIndex] = useState(0)
  const [operationIndex, setOperationIndex] = useState(0)
  const [timeIndex, setTimeIndex] = useState(2)
  const [sort, setSort] = useState<"asc" | "desc">("desc")
  const [search, setSearch] = useState("")
  const [event, setEvent] = useState("")
  const [session, setSession] = useState("")
  const [dialog, setDialog] = useState<AuditDialog>({ type: "none" })
  const [loading, setLoading] = useState(false)
  const refreshRequest = useRef(0)
  const refreshController = useRef<AbortController | null>(null)

  const nodes = useMemo(() => ["", ...machines.map((machine) => machine.name)], [machines])
  const selectedNode = nodes[nodeIndex] || ""
  const selectedOperation = OPERATIONS[operationIndex] || ""
  const timeRange = TIME_RANGES[timeIndex] || TIME_RANGES[2]!
  const current = entries[selected]
  const narrow = width < 70
  const tableHeight = Math.max(6, height - 15)
  const { rows, start } = useVisibleRows(entries, selected, tableHeight)

  const refresh = useCallback(async (force = false) => {
    if (refreshController.current && !force) return
    refreshController.current?.abort()
    const controller = new AbortController()
    refreshController.current = controller
    const requestId = ++refreshRequest.current
    setLoading(true)
    try {
      const now = Date.now() / 1000
      const payload = await api.audit(
        {
          limit: 800,
          node: selectedNode,
          operation: selectedOperation,
          event,
          session,
          search,
          start_ts: timeRange.seconds ? now - timeRange.seconds : undefined,
          sort,
        },
        controller.signal,
      )
      if (requestId !== refreshRequest.current || controller.signal.aborted) return
      setEntries(payload.entries)
      setSelected((value) => clampIndex(value, payload.entries.length))
      setStatus(`Audit: ${payload.total_matched} matching records`)
    } catch (error) {
      if (requestId === refreshRequest.current && !controller.signal.aborted) {
        setStatus(`Audit: ${formatError(error)}`)
      }
    } finally {
      if (refreshController.current === controller) refreshController.current = null
      if (requestId === refreshRequest.current) setLoading(false)
    }
  }, [event, search, selectedNode, selectedOperation, session, setStatus, sort, timeRange.seconds])

  useEffect(() => {
    refreshRequest.current += 1
    void refresh()
    return () => {
      refreshRequest.current += 1
      refreshController.current?.abort()
      refreshController.current = null
    }
  }, [refresh])

  useEffect(() => {
    onInteractionLockChange(dialog.type !== "none")
    return () => onInteractionLockChange(false)
  }, [dialog.type, onInteractionLockChange])

  useEffect(() => {
    const timer = setInterval(() => void refresh(), 5_000)
    return () => clearInterval(timer)
  }, [refresh])

  useKeyboard((key) => {
    if (!keyboardEnabled) return
    if (dialog.type !== "none") {
      if (key.name === "escape") setDialog({ type: "none" })
      return
    }
    if (key.name === "j" || key.name === "down") {
      setSelected((value) => clampIndex(value + 1, entries.length))
    }
    else if (key.name === "k" || key.name === "up") setSelected((value) => Math.max(0, value - 1))
    else if (key.name === "n") setNodeIndex((value) => (value + 1) % nodes.length)
    else if (key.name === "o") setOperationIndex((value) => (value + 1) % OPERATIONS.length)
    else if (key.name === "t") setTimeIndex((value) => (value + 1) % TIME_RANGES.length)
    else if (key.name === "s") setSort((value) => (value === "desc" ? "asc" : "desc"))
    else if (key.name === "/") setDialog({ type: "search" })
    else if (key.name === "e") setDialog({ type: "event" })
    else if (key.name === "i") setDialog({ type: "session" })
    else if (key.name === "c") {
      setSearch("")
      setEvent("")
      setSession("")
      setNodeIndex(0)
      setOperationIndex(0)
      setTimeIndex(2)
    } else if (key.name === "r") void refresh(true)
  })

  const applyDialog = (value: unknown) => {
    const submitted = typeof value === "string" ? value : ""
    if (dialog.type === "search") setSearch(submitted.trim())
    else if (dialog.type === "event") setEvent(submitted.trim())
    else if (dialog.type === "session") setSession(submitted.trim())
    setDialog({ type: "none" })
  }

  return (
    <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
      {width < 82 ? (
        <Panel title="Filters" active style={{ height: 3, alignItems: "center", justifyContent: "center" }}>
          <text
            fg={theme.muted}
            content={
              width < 58
                ? `N:${selectedNode || "*"} O:${selectedOperation || "*"} T:${timeRange.label} S:${sort.slice(0, 1).toUpperCase()}`
                : `${selectedNode || "All nodes"}  │  ${selectedOperation || "All ops"}  │  ${timeRange.label}  │  ${sort.toUpperCase()}`
            }
          />
        </Panel>
      ) : (
        <box style={{ height: 4, flexDirection: "row", gap: 1 }}>
          {[
            ["Node", selectedNode || "All", theme.cyan],
            ["Operation", selectedOperation || "All", theme.blue],
            ["Time", timeRange.label, theme.yellow],
            ["Sort", sort.toUpperCase(), theme.magenta],
          ].map(([title, value, color]) => (
            <Panel key={String(title)} title={String(title)} active style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
              <text fg={String(color)} attributes={1} content={String(value)} />
            </Panel>
          ))}
        </box>
      )}
      {(search || event || session) && (
        <box style={{ height: 2, flexDirection: "row", paddingLeft: 1, alignItems: "center", backgroundColor: theme.panelAlt }}>
          <text fg={theme.faint} content="Filters  " />
          {search && <text fg={theme.cyan} content={`search:${search}  `} />}
          {event && <text fg={theme.blue} content={`event:${event}  `} />}
          {session && <text fg={theme.yellow} content={`session:${session}  `} />}
        </box>
      )}
      <box style={{ flexGrow: 1, flexDirection: width >= 110 ? "row" : "column", gap: 1 }}>
        <Panel title={`Audit records · ${entries.length}${loading ? " · syncing" : ""}`} active style={{ flexGrow: 1, paddingTop: 1 }}>
          {entries.length === 0 ? (
            <EmptyState title="No matching audit records" detail="Adjust filters or wait for MCP activity" />
          ) : (
            <box style={{ flexDirection: "column", flexGrow: 1 }}>
              <box style={{ height: 2, flexDirection: "row", paddingLeft: 1, paddingRight: 1 }}>
                <text fg={theme.faint} content="TIME       " />
                {!narrow && <text fg={theme.faint} content="NODE              " />}
                {!narrow && <text fg={theme.faint} content="OPERATION     " />}
                <text fg={theme.faint} content="EVENT / TOOL" />
              </box>
              {rows.map((entry, offset) => {
                const index = start + offset
                const active = index === selected
                return (
                  <box
                    key={`${entry.ts}-${entry.event}-${index}`}
                    style={{
                      height: 1,
                      flexDirection: "row",
                      paddingLeft: 1,
                      paddingRight: 1,
                      backgroundColor: active ? theme.selectedStrong : index % 2 ? theme.panelAlt : undefined,
                    }}
                  >
                    <text fg={theme.faint} content={`${new Date(entry.ts * 1000).toLocaleTimeString().padEnd(11)} `} />
                    {!narrow && <text fg={active ? theme.text : theme.muted} content={`${entry.node.slice(0, 16).padEnd(17)} `} />}
                    {!narrow && <text fg={entryColor(entry)} content={`${entry.operation.slice(0, 12).padEnd(13)} `} />}
                    <text fg={active ? theme.text : theme.muted} attributes={active ? 1 : 0} content={entry.tool || entry.event} />
                  </box>
                )
              })}
            </box>
          )}
        </Panel>
        <Panel title="Record details" style={{ width: width >= 110 ? Math.max(36, Math.floor(width * 0.31)) : "100%", height: width >= 110 ? "100%" : 8, padding: 1 }}>
          {current ? (
            <scrollbox focused={false} style={{ flexGrow: 1 }} scrollY verticalScrollbarOptions={{ visible: true }}>
              <text fg={theme.cyan} attributes={1} content={current.tool || current.event} />
              <text fg={theme.faint} content={`${new Date(current.ts * 1000).toLocaleString()} · ${current.node}`} />
              <text fg={theme.muted} content={`\n${detail(current)}`} />
              <text fg={theme.faint} content={`\n\n${JSON.stringify(current, null, 2)}`} />
            </scrollbox>
          ) : (
            <EmptyState title="No record selected" detail="Use j/k to inspect entries" />
          )}
        </Panel>
      </box>
      <KeyHint
        items={[
          ["j/k", "move"],
          ["n", "node"],
          ["o", "operation"],
          ["t", "time"],
          ["s", "sort"],
          ["/", "search"],
          ["e/i", "event/session"],
          ["c", "clear"],
        ]}
      />
      {dialog.type !== "none" && (
        <Modal title={dialog.type === "search" ? "Search audit" : dialog.type === "event" ? "Filter event" : "Filter session"} height={7}>
          <text fg={theme.muted} content="Substring match; leave blank to clear" />
          <box style={{ height: 3, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input
              focused
              value={dialog.type === "search" ? search : dialog.type === "event" ? event : session}
              onSubmit={applyDialog}
            />
          </box>
          <text fg={theme.faint} content="Enter apply · Esc cancel" />
        </Modal>
      )}
    </box>
  )
}
