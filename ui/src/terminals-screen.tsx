import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, MachineSidebar, Modal, Panel, formatAge } from "./components"
import { theme } from "./theme"
import type { AuditEntry, Machine, TerminalSession } from "./types"

type TerminalDialog =
  | { type: "none" }
  | { type: "start"; name: string; cwd: string }
  | { type: "kill"; session: TerminalSession }

function encodeRawKey(key: {
  name: string
  ctrl?: boolean
  shift?: boolean
  option?: boolean
  sequence?: string
}): string | null {
  if (key.ctrl && key.name.length === 1) {
    const code = key.name.toUpperCase().charCodeAt(0) - 64
    if (code > 0 && code < 32) return String.fromCharCode(code)
  }
  const specials: Record<string, string> = {
    return: "\r",
    enter: "\r",
    backspace: "\x7f",
    tab: "\t",
    escape: "\x1b",
    up: "\x1b[A",
    down: "\x1b[B",
    right: "\x1b[C",
    left: "\x1b[D",
    home: "\x1b[H",
    end: "\x1b[F",
    delete: "\x1b[3~",
    pageup: "\x1b[5~",
    pagedown: "\x1b[6~",
  }
  if (specials[key.name]) return specials[key.name]
  if (key.sequence && key.sequence.length > 0) return key.sequence
  if (key.name.length === 1) return key.shift ? key.name.toUpperCase() : key.name
  return null
}

function AuditRail({ entries }: { entries: AuditEntry[] }) {
  return (
    <box style={{ flexDirection: "column", flexGrow: 1, paddingLeft: 1, paddingRight: 1 }}>
      {entries.length === 0 ? (
        <EmptyState title="No MCP activity" detail="Manual commands are intentionally excluded" />
      ) : (
        entries.slice(0, 40).map((entry) => {
          const ok = entry.ok
          return (
            <box key={`${entry.ts}-${entry.event}`} style={{ flexDirection: "column", marginBottom: 1 }}>
              <box style={{ flexDirection: "row" }}>
                <text fg={ok === false ? theme.red : ok === true ? theme.green : theme.cyan} content="● " />
                <text fg={theme.text} attributes={1} content={entry.tool || entry.event} />
              </box>
              <text fg={theme.faint} content={`${new Date(entry.ts * 1000).toLocaleTimeString()} · ${entry.node}`} />
              {entry.command && <text fg={theme.muted} content={String(entry.command).slice(0, 100)} />}
            </box>
          )
        })
      )}
    </box>
  )
}

export function TerminalsScreen({
  machines,
  machine,
  onMachine,
  width,
  height,
  setStatus,
}: {
  machines: Machine[]
  machine: string
  onMachine: (machine: string) => void
  width: number
  height: number
  setStatus: (message: string) => void
}) {
  const [sessions, setSessions] = useState<TerminalSession[]>([])
  const [selected, setSelected] = useState(0)
  const [output, setOutput] = useState("")
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [showAudit, setShowAudit] = useState(width >= 118)
  const [rawMode, setRawMode] = useState(false)
  const [dialog, setDialog] = useState<TerminalDialog>({ type: "none" })
  const [busy, setBusy] = useState(false)
  const selectedSession = sessions[selected]
  const compact = width < 96

  const refreshSessions = useCallback(async () => {
    try {
      const payload = await api.terminals(machine)
      setSessions(payload.sessions)
      setSelected((value) => Math.min(value, Math.max(0, payload.sessions.length - 1)))
    } catch (error) {
      setStatus(`Terminals: ${formatError(error)}`)
    }
  }, [machine, setStatus])

  const refreshOutput = useCallback(async () => {
    if (!selectedSession) {
      setOutput("")
      setAudit([])
      return
    }
    try {
      const [terminal, records] = await Promise.all([
        api.terminalRead(machine, selectedSession.session_id, Math.max(300, height * 8)),
        api.audit({ session: selectedSession.session_id, limit: 80, sort: "desc" }),
      ])
      setOutput(terminal.output)
      setAudit(records.entries)
    } catch (error) {
      setStatus(`Terminal: ${formatError(error)}`)
    }
  }, [height, machine, selectedSession, setStatus])

  useEffect(() => {
    void refreshSessions()
    const timer = setInterval(() => void refreshSessions(), 4_000)
    return () => clearInterval(timer)
  }, [refreshSessions])

  useEffect(() => {
    void refreshOutput()
    const timer = setInterval(() => void refreshOutput(), 900)
    return () => clearInterval(timer)
  }, [refreshOutput])

  useEffect(() => {
    if (width < 105) setShowAudit(false)
  }, [width])

  const send = async (inputText: string, enter = true) => {
    if (!selectedSession || inputText.length === 0) return
    setBusy(true)
    try {
      await api.terminalAction("send", {
        machine,
        session_id: selectedSession.session_id,
        input_text: inputText,
        enter,
      })
      await new Promise((resolve) => setTimeout(resolve, 80))
      await refreshOutput()
    } catch (error) {
      setStatus(`Send: ${formatError(error)}`)
    } finally {
      setBusy(false)
    }
  }

  const sendRaw = (inputText: string) => {
    if (!selectedSession || inputText.length === 0) return
    void api
      .terminalAction("send", {
        machine,
        session_id: selectedSession.session_id,
        input_text: inputText,
        enter: false,
      })
      .catch((error) => setStatus(`Raw input: ${formatError(error)}`))
  }

  const startSession = async (value: string) => {
    const [namePart, ...cwdParts] = value.trim().split(/\s+/)
    try {
      await api.terminalAction("start", {
        machine,
        name: namePart || undefined,
        cwd: cwdParts.join(" ") || ".",
      })
      setDialog({ type: "none" })
      await refreshSessions()
      setSelected(Math.max(0, sessions.length))
    } catch (error) {
      setStatus(`Start: ${formatError(error)}`)
    }
  }

  const switchMachine = (delta: number) => {
    if (!machines.length) return
    const index = Math.max(0, machines.findIndex((item) => item.name === machine))
    const next = (index + delta + machines.length) % machines.length
    onMachine(machines[next]!.name)
    setSelected(0)
  }

  useKeyboard((key) => {
    if (dialog.type === "start") {
      if (key.name === "escape") setDialog({ type: "none" })
      return
    }
    if (dialog.type === "kill") {
      if (key.name === "escape" || key.name === "n") setDialog({ type: "none" })
      if (key.name === "y" || key.name === "return") {
        void api
          .terminalAction("kill", { machine, session_id: dialog.session.session_id })
          .then(async () => {
            setDialog({ type: "none" })
            await refreshSessions()
          })
          .catch((error) => setStatus(`Kill: ${formatError(error)}`))
      }
      return
    }
    if (rawMode) {
      if (key.ctrl && key.name === "t") {
        setRawMode(false)
        setStatus("Raw input disabled")
        return
      }
      const encoded = encodeRawKey(key)
      if (encoded !== null) sendRaw(encoded)
      return
    }

    if (key.ctrl && key.name === "t") {
      if (selectedSession) {
        setRawMode(true)
        setStatus("Raw input enabled · Ctrl+T to leave")
      }
    } else if (key.option && key.name === "[") switchMachine(-1)
    else if (key.option && key.name === "]") switchMachine(1)
    else if (key.option && key.name === "left") setSelected((value) => Math.max(0, value - 1))
    else if (key.option && key.name === "right") setSelected((value) => Math.min(sessions.length - 1, value + 1))
    else if (key.ctrl && key.name === "n") setDialog({ type: "start", name: "", cwd: "." })
    else if (key.ctrl && key.name === "w" && selectedSession) setDialog({ type: "kill", session: selectedSession })
    else if (key.ctrl && key.name === "a") setShowAudit((value) => !value)
    else if (key.ctrl && key.name === "r") void refreshOutput()
  })

  const outputLines = useMemo(() => output.split("\n"), [output])
  const terminalHeight = Math.max(8, height - 12)
  const visibleOutput = outputLines.slice(-terminalHeight).join("\n")

  return (
    <box style={{ flexGrow: 1, flexDirection: "column" }}>
      <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
        {!compact && <MachineSidebar machines={machines} selected={machine} />}
        <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
          <box style={{ height: 2, flexDirection: "row", alignItems: "center", paddingLeft: 1 }}>
            <text fg={theme.faint} content={`${machine} / `} />
            <text
              fg={selectedSession ? theme.cyan : theme.faint}
              attributes={selectedSession ? 1 : 0}
              content={selectedSession?.session_id || "no terminal"}
            />
            <box style={{ flexGrow: 1 }} />
            {rawMode && <text fg={theme.orange} attributes={1} content="RAW INPUT  " />}
            {busy && <text fg={theme.yellow} content="sending  " />}
            <text fg={theme.faint} content={`${selectedSession?.backend || "—"}  `} />
          </box>
          <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
            <Panel title="Terminal" active style={{ flexGrow: 1, padding: 1 }}>
              {selectedSession ? (
                <text fg={theme.text} content={visibleOutput || "Terminal is ready."} />
              ) : (
                <EmptyState title="No persistent terminal" detail="Press n to create one" />
              )}
            </Panel>
            {showAudit && (
              <Panel title="MCP audit · manual input excluded" style={{ width: Math.max(30, Math.floor(width * 0.28)) }}>
                <AuditRail entries={audit} />
              </Panel>
            )}
          </box>
          <box style={{ height: 3, flexDirection: "row", gap: 1 }}>
            <Panel title="Command" active={Boolean(selectedSession)} style={{ flexGrow: 1, paddingLeft: 1, paddingRight: 1 }}>
              <input
                key={selectedSession?.session_id || "no-session"}
                focused={Boolean(selectedSession) && !rawMode && dialog.type === "none"}
                placeholder={selectedSession ? "Enter a command…" : "Create a terminal first"}
                onSubmit={(value: unknown) => void send(typeof value === "string" ? value : "", true)}
              />
            </Panel>
          </box>
          <box
            style={{
              height: 3,
              flexDirection: "row",
              alignItems: "center",
              border: true,
              borderStyle: "rounded",
              borderColor: theme.border,
              backgroundColor: theme.panel,
              paddingLeft: 1,
              paddingRight: 1,
            }}
          >
            {sessions.map((session, index) => (
              <box
                key={session.session_id}
                style={{
                  height: 1,
                  marginRight: 1,
                  paddingLeft: 1,
                  paddingRight: 1,
                  backgroundColor: index === selected ? theme.selectedStrong : theme.panelAlt,
                }}
              >
                <text
                  fg={index === selected ? theme.cyan : theme.muted}
                  attributes={index === selected ? 1 : 0}
                  content={session.session_id}
                />
              </box>
            ))}
            {sessions.length === 0 && <text fg={theme.faint} content="No sessions" />}
            <box style={{ flexGrow: 1 }} />
            {selectedSession?.created && (
              <text fg={theme.faint} content={formatAge(Number(selectedSession.created))} />
            )}
          </box>
        </box>
      </box>
      <KeyHint
        items={[
          ["Alt+←/→", "terminal"],
          ["Ctrl+N", "new"],
          ["Ctrl+W", "kill"],
          ["Ctrl+A", "audit"],
          ["Ctrl+T", "raw mode"],
          ["Alt+[ / ]", "machine"],
          ["Ctrl+R", "refresh"],
        ]}
      />
      {dialog.type === "start" && (
        <Modal title="New persistent terminal" height={8}>
          <text fg={theme.muted} content="Enter: name [working-directory]" />
          <box style={{ height: 3, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused placeholder="terminal-name ." onSubmit={(value: unknown) => void startSession(typeof value === "string" ? value : "")} />
          </box>
          <text fg={theme.faint} content="Enter create · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "kill" && (
        <Modal title="Kill terminal" height={7}>
          <text fg={theme.red} attributes={1} content={`Kill ${dialog.session.session_id}?`} />
          <text fg={theme.muted} content="The persistent process and its session will stop." />
          <text fg={theme.faint} content="y / Enter confirm · n / Esc cancel" />
        </Modal>
      )}
    </box>
  )
}
