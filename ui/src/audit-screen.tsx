import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, formatError } from "./api"
import {
  AUDIT_OPERATIONS,
  auditInput,
  auditOutput,
  formatAuditValue,
  selectionAfterRefresh,
} from "./audit-utils"
import { EmptyState, KeyHint, Modal, Panel, useVisibleRows } from "./components"
import { clampIndex } from "./state-utils"
import { screenTheme, theme } from "./theme"
import type { AuditEntry, Machine } from "./types"

const colors = screenTheme.Audit

type AuditDialog = { type: "none" } | { type: "search" } | { type: "event" } | { type: "session" }

const TIME_RANGES = [
  { label: "15m", seconds: 15 * 60 },
  { label: "1h", seconds: 60 * 60 },
  { label: "24h", seconds: 24 * 60 * 60 },
  { label: "7d", seconds: 7 * 24 * 60 * 60 },
  { label: "All", seconds: 0 },
]

function entryColor(entry: AuditEntry): string {
  if (entry.paired === false) return theme.yellow
  if (entry.ok === false || entry.error || entry.status === "failed") return theme.red
  if (entry.ok === true || entry.status === "success") return theme.green
  if (entry.event.endsWith("_start")) return theme.yellow
  return theme.muted
}

function statusLabel(entry: AuditEntry): string {
  if (entry.paired === false) return entry.status === "running" ? "RUNNING" : "UNPAIRED"
  if (entry.ok === false || entry.error || entry.status === "failed") return "FAILED"
  if (entry.ok === true || entry.status === "success") return "SUCCESS"
  return entry.status?.toUpperCase() || "EVENT"
}

function durationLabel(entry: AuditEntry): string {
  if (typeof entry.duration_ms !== "number") return ""
  if (entry.duration_ms < 1000) return `${entry.duration_ms} ms`
  return `${(entry.duration_ms / 1000).toFixed(2)} s`
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
  const [detail, setDetail] = useState<AuditEntry | null>(null)
  const refreshRequest = useRef(0)
  const refreshController = useRef<AbortController | null>(null)
  const detailRequest = useRef(0)
  const detailController = useRef<AbortController | null>(null)
  const entriesRef = useRef<AuditEntry[]>([])
  const selectedRef = useRef(0)

  const nodes = useMemo(() => ["", ...machines.map((machine) => machine.name)], [machines])
  const selectedNode = nodes[nodeIndex] || ""
  const selectedOperation = AUDIT_OPERATIONS[operationIndex] || ""
  const timeRange = TIME_RANGES[timeIndex] || TIME_RANGES[2]!
  const current = entries[selected]
  const displayed = detail?.id === current?.id ? detail : current
  const narrow = width < 70
  const tableHeight = Math.max(6, height - 15)
  const { rows, start } = useVisibleRows(entries, selected, tableHeight)

  const selectIndex = useCallback((next: number | ((value: number) => number)) => {
    const resolved = typeof next === "function" ? next(selectedRef.current) : next
    selectedRef.current = resolved
    setSelected(resolved)
  }, [])

  const cycleNode = () => setNodeIndex((value) => (value + 1) % nodes.length)
  const cycleOperation = () => setOperationIndex((value) => (value + 1) % AUDIT_OPERATIONS.length)
  const cycleTime = () => setTimeIndex((value) => (value + 1) % TIME_RANGES.length)
  const toggleSort = () => setSort((value) => (value === "desc" ? "asc" : "desc"))

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
      const nextSelected = selectionAfterRefresh(entriesRef.current, selectedRef.current, payload.entries)
      entriesRef.current = payload.entries
      selectedRef.current = nextSelected
      setEntries(payload.entries)
      setSelected(nextSelected)
      setStatus(`Audit: ${payload.total_matched} matching calls and events`)
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
    detailController.current?.abort()
    const controller = new AbortController()
    detailController.current = controller
    const requestId = ++detailRequest.current
    setDetail(null)
    if (!current?.id) return () => controller.abort()
    void api
      .auditDetail(current.id, controller.signal)
      .then((entry) => {
        if (requestId === detailRequest.current && !controller.signal.aborted) setDetail(entry)
      })
      .catch((error) => {
        if (requestId === detailRequest.current && !controller.signal.aborted) {
          setStatus(`Audit detail: ${formatError(error)}`)
        }
      })
    return () => {
      detailRequest.current += 1
      controller.abort()
      if (detailController.current === controller) detailController.current = null
    }
  }, [current?.id, current?.paired, current?.status, setStatus])

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
      selectIndex((value) => clampIndex(value + 1, entries.length))
    } else if (key.name === "k" || key.name === "up") {
      selectIndex((value) => Math.max(0, value - 1))
    } else if (key.name === "n") cycleNode()
    else if (key.name === "o") cycleOperation()
    else if (key.name === "t") cycleTime()
    else if (key.name === "s") toggleSort()
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

  const outputText = displayed
    ? formatAuditValue(auditOutput(displayed), "No return value recorded")
    : ""
  const inputText = displayed ? formatAuditValue(auditInput(displayed), "No input recorded") : ""
  const duration = displayed ? durationLabel(displayed) : ""
  const detailHeight = width >= 110 ? "100%" : Math.max(14, Math.floor(height * 0.42))

  return (
    <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
      {width < 82 ? (
        <Panel title="Filters" active accent={colors.accent} activeBackground={colors.panel} style={{ height: 3, alignItems: "center", justifyContent: "center" }}>
          <box style={{ flexDirection: "row" }}>
            <text onMouseDown={cycleNode} fg={colors.accent} content={`N:${selectedNode || "*"}  `} />
            <text onMouseDown={cycleOperation} fg={theme.blue} content={`O:${selectedOperation || "*"}  `} />
            <text onMouseDown={cycleTime} fg={theme.yellow} content={`T:${timeRange.label}  `} />
            <text onMouseDown={toggleSort} fg={theme.magenta} content={`S:${sort.slice(0, 1).toUpperCase()}`} />
          </box>
        </Panel>
      ) : (
        <box style={{ height: 4, flexDirection: "row", gap: 1 }}>
          {[
            { title: "Node", value: selectedNode || "All", color: colors.accent, action: cycleNode },
            { title: "Operation", value: selectedOperation || "All", color: theme.blue, action: cycleOperation },
            { title: "Time", value: timeRange.label, color: theme.yellow, action: cycleTime },
            { title: "Sort", value: sort.toUpperCase(), color: theme.magenta, action: toggleSort },
          ].map(({ title, value, color, action }) => (
            <Panel key={title} title={title} active accent={colors.accent} activeBackground={colors.panel} onMouseDown={action} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
              <text fg={color} attributes={1} content={value} />
            </Panel>
          ))}
        </box>
      )}
      {(search || event || session) && (
        <box style={{ height: 2, flexDirection: "row", paddingLeft: 1, alignItems: "center", backgroundColor: theme.panelAlt }}>
          <text fg={theme.faint} content="Filters  " />
          {search && <text fg={colors.accent} content={`search:${search}  `} />}
          {event && <text fg={theme.blue} content={`event:${event}  `} />}
          {session && <text fg={theme.yellow} content={`session:${session}  `} />}
        </box>
      )}
      <box style={{ flexGrow: 1, flexDirection: width >= 110 ? "row" : "column", gap: 1 }}>
        <Panel title={`Audit records · ${entries.length}${loading ? " · syncing" : ""}`} active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, paddingTop: 1 }}>
          {entries.length === 0 ? (
            <EmptyState title="No matching audit records" detail="Adjust filters or wait for MCP activity" />
          ) : (
            <box style={{ flexDirection: "column", flexGrow: 1 }}>
              <box style={{ height: 2, flexDirection: "row", paddingLeft: 1, paddingRight: 1 }}>
                <text fg={theme.faint} content="TIME       " />
                {!narrow && <text fg={theme.faint} content="NODE              " />}
                {!narrow && <text fg={theme.faint} content="OPERATION  " />}
                <text fg={theme.faint} content="EVENT / TOOL" />
              </box>
              {rows.map((entry, offset) => {
                const index = start + offset
                const active = index === selected
                return (
                  <box
                    key={entry.id || `${entry.ts}-${entry.event}-${index}`}
                    onMouseDown={() => selectIndex(index)}
                    style={{
                      height: 1,
                      flexDirection: "row",
                      paddingLeft: 1,
                      paddingRight: 1,
                      backgroundColor: active ? colors.selected : index % 2 ? theme.panelAlt : undefined,
                    }}
                  >
                    <text fg={theme.faint} content={`${new Date(entry.ts * 1000).toLocaleTimeString().padEnd(11)} `} />
                    {!narrow && <text fg={active ? theme.text : theme.muted} content={`${entry.node.slice(0, 16).padEnd(17)} `} />}
                    {!narrow && <text fg={entryColor(entry)} content={`${entry.operation.slice(0, 9).padEnd(10)} `} />}
                    <text fg={active ? theme.text : theme.muted} attributes={active ? 1 : 0} content={entry.tool || entry.event} />
                  </box>
                )
              })}
            </box>
          )}
        </Panel>
        <Panel
          title="Call details"
          style={{
            width: width >= 110 ? Math.max(44, Math.floor(width * 0.38)) : "100%",
            height: detailHeight,
            padding: 1,
            gap: 1,
          }}
        >
          {displayed ? (
            <>
              <box style={{ height: 1, flexDirection: "row" }}>
                <text fg={colors.accent} attributes={1} content={displayed.tool || displayed.event} />
                <box style={{ flexGrow: 1 }} />
                <text fg={entryColor(displayed)} attributes={1} content={statusLabel(displayed)} />
              </box>
              <text
                fg={theme.faint}
                content={`${new Date(displayed.ts * 1000).toLocaleString()} · ${displayed.node}${duration ? ` · ${duration}` : ""}`}
              />
              <Panel title="Call result" style={{ flexGrow: 1, padding: 1 }}>
                <scrollbox focused={false} style={{ flexGrow: 1 }} scrollY verticalScrollbarOptions={{ visible: true }}>
                  <text fg={theme.muted} content={outputText} />
                </scrollbox>
              </Panel>
              <Panel title="Call input" style={{ flexGrow: 1, padding: 1 }}>
                <scrollbox focused={false} style={{ flexGrow: 1 }} scrollY verticalScrollbarOptions={{ visible: true }}>
                  <text fg={theme.faint} content={inputText} />
                </scrollbox>
              </Panel>
            </>
          ) : (
            <EmptyState title="No record selected" detail="Use j/k to inspect entries" />
          )}
        </Panel>
      </box>
      <KeyHint
        accent={colors.accent}
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
