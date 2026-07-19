import type { InputRenderable, MouseEvent as OpenTUIMouseEvent } from "@opentui/core"
import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, Loading, MachineSidebar, Modal, Panel, formatAge } from "./components"
import { clampIndex, scopedItems } from "./state-utils"
import {
  terminalDisplayRows,
  terminalScrollLimit,
  terminalViewportRows,
  visibleTerminalLines,
} from "./terminal-output"
import { screenTheme, theme } from "./theme"
import type { AuditEntry, Machine, TerminalSession } from "./types"

const colors = screenTheme.Terminals

type TerminalDialog =
  | { type: "none" }
  | { type: "start"; machine: string; name: string; cwd: string }
  | { type: "kill"; machine: string; session: TerminalSession }

function encodeRawKey(key: {
  name: string
  ctrl?: boolean
  shift?: boolean
  option?: boolean
  meta?: boolean
  sequence?: string
}): string | null {
  const alt = Boolean(key.option || key.meta)
  if (alt && key.name.length === 1) {
    return `\x1b${key.shift ? key.name.toUpperCase() : key.name}`
  }
  if (alt && key.sequence?.startsWith("\x1b")) return key.sequence
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
                <text fg={ok === false ? theme.red : ok === true ? theme.green : colors.accent} content="● " />
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
  onRawModeChange,
  keyboardEnabled,
  onInteractionLockChange,
}: {
  machines: Machine[]
  machine: string
  onMachine: (machine: string) => void
  width: number
  height: number
  setStatus: (message: string) => void
  onRawModeChange: (enabled: boolean) => void
  keyboardEnabled: boolean
  onInteractionLockChange: (locked: boolean) => void
}) {
  const [sessions, setSessions] = useState<TerminalSession[]>([])
  const [sessionsMachine, setSessionsMachine] = useState<string | null>(null)
  const [sessionsError, setSessionsError] = useState<string | null>(null)
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [output, setOutput] = useState("")
  const [outputScope, setOutputScope] = useState<string | null>(null)
  const [outputError, setOutputError] = useState<{ scope: string; message: string } | null>(null)
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [showAudit, setShowAudit] = useState(width >= 118)
  const [rawMode, setRawMode] = useState(false)
  const [scrollOffset, setScrollOffset] = useState(0)
  const [dialog, setDialog] = useState<TerminalDialog>({ type: "none" })
  const [busy, setBusy] = useState(false)
  const commandInputRef = useRef<InputRenderable | null>(null)
  const scrollOffsetRef = useRef(0)
  const pendingOutputRef = useRef<string | null>(null)
  const rawQueue = useRef<Promise<void>>(Promise.resolve())
  const sessionsRequest = useRef(0)
  const outputRequest = useRef(0)
  const sessionsController = useRef<AbortController | null>(null)
  const outputController = useRef<AbortController | null>(null)
  const machineRef = useRef(machine)
  const sessionsReady = sessionsMachine === machine
  const activeSessions = scopedItems(sessionsMachine, machine, sessions)
  const selectedSession = activeSessions.find((session) => session.session_id === selectedSessionId)
    || activeSessions[0]
  const selectedOutputScope = selectedSession ? `${machine}\u0000${selectedSession.session_id}` : null
  const outputReady = selectedOutputScope !== null && outputScope === selectedOutputScope
  const selectedOutputError = outputError?.scope === selectedOutputScope ? outputError.message : null
  const selected = Math.max(0, activeSessions.findIndex((session) => session.session_id === selectedSession?.session_id))
  const selectedSessionIdRef = useRef<string | null>(selectedSession?.session_id || null)
  machineRef.current = machine
  selectedSessionIdRef.current = selectedSession?.session_id || null
  const compact = width < 96
  const sidebarColumns = compact ? 0 : 24
  const auditColumns = showAudit ? Math.max(30, Math.floor(width * 0.28)) + 1 : 0
  const terminalColumns = Math.max(20, width - sidebarColumns - auditColumns - 6)
  const terminalRows = terminalViewportRows(height)
  const outputRows = useMemo(
    () => terminalDisplayRows(output, terminalColumns),
    [output, terminalColumns],
  )
  const maxScrollOffset = terminalScrollLimit(outputRows.length, terminalRows)
  const safeScrollOffset = Math.min(scrollOffset, maxScrollOffset)
  const visibleLines = visibleTerminalLines(outputRows, terminalRows, safeScrollOffset)

  const scrollOutput = useCallback((delta: number) => {
    setScrollOffset((current) => {
      const next = Math.max(0, Math.min(maxScrollOffset, current + delta))
      scrollOffsetRef.current = next
      return next
    })
  }, [maxScrollOffset])

  const handleOutputScroll = (event: OpenTUIMouseEvent) => {
    const direction = event.scroll?.direction
    if (direction !== "up" && direction !== "down") return
    event.preventDefault()
    event.stopPropagation()
    const amount = Math.max(1, Math.ceil(Math.abs(event.scroll?.delta || 1))) * 3
    scrollOutput(direction === "up" ? amount : -amount)
  }

  const selectSession = useCallback((index: number) => {
    const nextIndex = clampIndex(index, activeSessions.length)
    const nextSessionId = activeSessions[nextIndex]?.session_id || null
    selectedSessionIdRef.current = nextSessionId
    setSelectedSessionId(nextSessionId)
  }, [activeSessions])

  const refreshSessions = useCallback(async (force = false): Promise<TerminalSession[]> => {
    if (sessionsController.current && !force) return []
    sessionsController.current?.abort()
    const controller = new AbortController()
    sessionsController.current = controller
    const requestId = ++sessionsRequest.current
    const targetMachine = machine
    setSessionsError(null)
    try {
      const payload = await api.terminals(targetMachine, controller.signal)
      if (
        requestId !== sessionsRequest.current ||
        machineRef.current !== targetMachine ||
        controller.signal.aborted
      ) return []
      setSessions(payload.sessions)
      setSessionsMachine(targetMachine)
      setSessionsError(null)
      setSelectedSessionId((current) => {
        const preferred = selectedSessionIdRef.current || current
        const nextSessionId = preferred && payload.sessions.some((session) => session.session_id === preferred)
          ? preferred
          : payload.sessions[0]?.session_id || null
        selectedSessionIdRef.current = nextSessionId
        return nextSessionId
      })
      return payload.sessions
    } catch (error) {
      if (!controller.signal.aborted && machineRef.current === targetMachine) {
        const message = formatError(error)
        setSessionsError(message)
        setStatus(`Terminals: ${message}`)
      }
      return []
    } finally {
      if (sessionsController.current === controller) sessionsController.current = null
    }
  }, [machine, setStatus])

  const refreshOutput = useCallback(async (force = false) => {
    if (outputController.current && !force) return
    outputController.current?.abort()
    const controller = new AbortController()
    outputController.current = controller
    const requestId = ++outputRequest.current
    const targetMachine = machine
    const targetSession = selectedSession?.session_id || null
    if (!targetSession) {
      outputController.current = null
      setOutput("")
      setOutputScope(null)
      setOutputError(null)
      setAudit([])
      return
    }
    const targetScope = `${targetMachine}\u0000${targetSession}`
    setOutputError((current) => current?.scope === targetScope ? null : current)
    try {
      const [terminal, records] = await Promise.all([
        api.terminalRead(
          targetMachine,
          targetSession,
          Math.max(300, height * 8),
          controller.signal,
        ),
        api.audit(
          { node: targetMachine, session: targetSession, limit: 80, sort: "desc" },
          controller.signal,
        ),
      ])
      if (
        requestId !== outputRequest.current ||
        machineRef.current !== targetMachine ||
        selectedSessionIdRef.current !== targetSession ||
        controller.signal.aborted
      ) return
      if (scrollOffsetRef.current > 0) pendingOutputRef.current = terminal.output
      else setOutput(terminal.output)
      setOutputScope(targetScope)
      setOutputError(null)
      setAudit(records.entries)
    } catch (error) {
      if (!controller.signal.aborted && machineRef.current === targetMachine && selectedSessionIdRef.current === targetSession) {
        const message = formatError(error)
        setOutputError({ scope: targetScope, message })
        setStatus(`Terminal: ${message}`)
      }
    } finally {
      if (outputController.current === controller) outputController.current = null
    }
  }, [height, machine, selectedSession, setStatus])

  useEffect(() => {
    sessionsRequest.current += 1
    outputRequest.current += 1
    setSessions([])
    setSessionsMachine(null)
    setSessionsError(null)
    setSelectedSessionId(null)
    selectedSessionIdRef.current = null
    setOutput("")
    setOutputScope(null)
    setOutputError(null)
    pendingOutputRef.current = null
    scrollOffsetRef.current = 0
    setScrollOffset(0)
    setAudit([])
    setDialog({ type: "none" })
    setRawMode(false)
    void refreshSessions()
    const timer = setInterval(() => void refreshSessions(), 4_000)
    return () => {
      sessionsRequest.current += 1
      sessionsController.current?.abort()
      sessionsController.current = null
      clearInterval(timer)
    }
  }, [machine, refreshSessions])

  useEffect(() => {
    outputRequest.current += 1
    void refreshOutput()
    const timer = setInterval(() => void refreshOutput(), 900)
    return () => {
      outputRequest.current += 1
      outputController.current?.abort()
      outputController.current = null
      clearInterval(timer)
    }
  }, [refreshOutput])

  useEffect(() => {
    if (width < 105) setShowAudit(false)
  }, [width])

  useEffect(() => {
    onInteractionLockChange(dialog.type !== "none")
    return () => onInteractionLockChange(false)
  }, [dialog.type, onInteractionLockChange])

  useEffect(() => {
    onRawModeChange(rawMode)
    return () => onRawModeChange(false)
  }, [onRawModeChange, rawMode])

  useEffect(() => {
    if (!selectedSession && rawMode) setRawMode(false)
  }, [rawMode, selectedSession])

  useEffect(() => {
    pendingOutputRef.current = null
    scrollOffsetRef.current = 0
    setScrollOffset(0)
  }, [machine, selectedSession?.session_id])

  useEffect(() => {
    if (!selectedSession) return
    const targetMachine = machine
    const sessionId = selectedSession.session_id
    const timer = setTimeout(() => {
      void api.terminalAction("resize", {
        machine: targetMachine,
        session_id: sessionId,
        cols: terminalColumns,
        rows: terminalRows,
      }).catch((error) => {
        if (
          machineRef.current === targetMachine
          && selectedSessionIdRef.current === sessionId
        ) setStatus(`Resize: ${formatError(error)}`)
      })
    }, 120)
    return () => clearTimeout(timer)
  }, [machine, selectedSession?.session_id, setStatus, terminalColumns, terminalRows])

  useEffect(() => {
    const clamped = Math.min(scrollOffset, maxScrollOffset)
    if (clamped !== scrollOffset) setScrollOffset(clamped)
    scrollOffsetRef.current = clamped
    if (clamped === 0 && pendingOutputRef.current !== null) {
      const pending = pendingOutputRef.current
      pendingOutputRef.current = null
      setOutput(pending)
    }
  }, [maxScrollOffset, scrollOffset])

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
      await refreshOutput(true)
    } catch (error) {
      setStatus(`Send: ${formatError(error)}`)
    } finally {
      setBusy(false)
    }
  }

  const sendRaw = (inputText: string) => {
    if (!selectedSession || inputText.length === 0) return
    const targetMachine = machine
    const sessionId = selectedSession.session_id
    rawQueue.current = rawQueue.current
      .then(async () => {
        await api.terminalAction("send", {
          machine: targetMachine,
          session_id: sessionId,
          input_text: inputText,
          enter: false,
        })
      })
      .catch((error) => setStatus(`Raw input: ${formatError(error)}`))
  }

  const submitCommand = (value: string) => {
    if (!selectedSession || value.length === 0) return
    pendingOutputRef.current = null
    scrollOffsetRef.current = 0
    setScrollOffset(0)
    setTimeout(() => {
      if (commandInputRef.current) commandInputRef.current.value = ""
    }, 0)
    void send(value, true)
  }

  const startSession = async (value: string) => {
    if (dialog.type !== "start" || dialog.machine !== machine) {
      setDialog({ type: "none" })
      return
    }
    const [namePart, ...cwdParts] = value.trim().split(/\s+/)
    try {
      const created = await api.terminalAction<{ session_id: string }>("start", {
        machine: dialog.machine,
        name: namePart || undefined,
        cwd: cwdParts.join(" ") || ".",
      })
      setDialog({ type: "none" })
      selectedSessionIdRef.current = created.session_id
      setSelectedSessionId(created.session_id)
      const nextSessions = await refreshSessions(true)
      const createdSession = nextSessions.find((session) => session.session_id === created.session_id)
        || nextSessions.find((session) => session.session_id === namePart)
      const nextSessionId = createdSession?.session_id || created.session_id
      selectedSessionIdRef.current = nextSessionId
      setSelectedSessionId(nextSessionId)
      setStatus(`Started ${nextSessionId}`)
    } catch (error) {
      setStatus(`Start: ${formatError(error)}`)
    }
  }

  const switchMachine = (delta: number) => {
    if (!machines.length) return
    const index = Math.max(0, machines.findIndex((item) => item.name === machine))
    const next = (index + delta + machines.length) % machines.length
    setSessions([])
    setSessionsMachine(null)
    setSessionsError(null)
    setSelectedSessionId(null)
    selectedSessionIdRef.current = null
    setOutput("")
    setOutputScope(null)
    setOutputError(null)
    pendingOutputRef.current = null
    scrollOffsetRef.current = 0
    setScrollOffset(0)
    setAudit([])
    setDialog({ type: "none" })
    setRawMode(false)
    onMachine(machines[next]!.name)
  }

  const startTerminal = () => setDialog({ type: "start", machine, name: "", cwd: "." })
  const killTerminal = () => selectedSession && setDialog({ type: "kill", machine, session: selectedSession })
  const toggleAudit = () => setShowAudit((value) => !value)
  const toggleRawMode = () => {
    if (rawMode) {
      setRawMode(false)
      setStatus("Raw input disabled")
    } else if (selectedSession) {
      setRawMode(true)
      setStatus("Raw input enabled · F8 to leave")
    }
  }
  const footerLocked = !keyboardEnabled || dialog.type !== "none"
  const standardFooterLocked = footerLocked || rawMode

  useKeyboard((key) => {
    if (!keyboardEnabled) return
    if (dialog.type !== "none" && dialog.machine !== machine) {
      setDialog({ type: "none" })
      return
    }
    if (dialog.type === "start") {
      if (key.name === "escape") setDialog({ type: "none" })
      return
    }
    if (dialog.type === "kill") {
      if (key.name === "escape" || key.name === "n") setDialog({ type: "none" })
      if (key.name === "y" || key.name === "return") {
        void api
          .terminalAction("kill", {
            machine: dialog.machine,
            session_id: dialog.session.session_id,
          })
          .then(async () => {
            setDialog({ type: "none" })
            await refreshSessions(true)
          })
          .catch((error) => setStatus(`Kill: ${formatError(error)}`))
      }
      return
    }
    if (rawMode) {
      key.preventDefault()
      key.stopPropagation()
      if (key.name === "f8") {
        toggleRawMode()
        return
      }
      const encoded = encodeRawKey(key)
      if (encoded !== null) sendRaw(encoded)
      return
    }

    if (key.name === "f8") toggleRawMode()
    else if (key.name === "pageup" && selectedSession) {
      key.preventDefault()
      key.stopPropagation()
      scrollOutput(terminalRows)
    } else if (key.name === "pagedown" && selectedSession) {
      key.preventDefault()
      key.stopPropagation()
      scrollOutput(-terminalRows)
    } else if ((key.option || key.meta) && key.name === "[") switchMachine(-1)
    else if ((key.option || key.meta) && key.name === "]") switchMachine(1)
    else if ((key.option || key.meta) && key.name === "left") selectSession(selected - 1)
    else if ((key.option || key.meta) && key.name === "right") selectSession(selected + 1)
    else if ((key.option || key.meta) && key.name === "n") startTerminal()
    else if ((key.option || key.meta) && key.name === "w") killTerminal()
    else if ((key.option || key.meta) && key.name === "a") toggleAudit()
    else if ((key.option || key.meta) && key.name === "r") void refreshOutput(true)
  })

  return (
    <box style={{ flexGrow: 1, flexDirection: "column" }}>
      <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
        {!compact && (
          <MachineSidebar
            machines={machines}
            selected={machine}
            accent={colors.accent}
            selectedColor={colors.selected}
            onSelect={(nextMachine) => {
              if (nextMachine === machine) return
              setSessions([])
              setSessionsMachine(null)
              setSessionsError(null)
              setSelectedSessionId(null)
              selectedSessionIdRef.current = null
              setOutput("")
              setOutputScope(null)
              setOutputError(null)
              setAudit([])
              setDialog({ type: "none" })
              setRawMode(false)
              onMachine(nextMachine)
            }}
          />
        )}
        <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
          <box style={{ height: 2, flexDirection: "row", alignItems: "center", paddingLeft: 1 }}>
            <text fg={theme.faint} content={`${machine} / `} />
            <text
              fg={selectedSession ? colors.accent : theme.faint}
              attributes={selectedSession ? 1 : 0}
              content={sessionsReady ? selectedSession?.session_id || "no terminal" : sessionsError ? "unavailable" : "loading terminals"}
            />
            <box style={{ flexGrow: 1 }} />
            {rawMode && <text fg={theme.orange} attributes={1} content="RAW INPUT  " />}
            {safeScrollOffset > 0 && <text fg={theme.yellow} content={`history -${safeScrollOffset}  `} />}
            {busy && <text fg={theme.yellow} content="sending  " />}
            <text fg={theme.faint} content={`${selectedSession?.backend || "—"}  `} />
          </box>
          <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
            <Panel title="Terminal" active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, padding: 1 }}>
              {!sessionsReady ? (
                sessionsError ? <EmptyState title="Terminals unavailable" detail="Switch machines or retry shortly" /> : <Loading label="Loading terminals" />
              ) : selectedSession ? (
                !outputReady ? (
                  selectedOutputError ? <EmptyState title="Terminal output unavailable" detail="Press Alt+R to try again" /> : <Loading label="Loading terminal output" />
                ) : (
                  <box
                    onMouseScroll={handleOutputScroll}
                    style={{ flexGrow: 1, flexDirection: "column" }}
                  >
                    {visibleLines.map((line, index) => (
                      <text key={`${index}-${line}`} fg={theme.text} wrapMode="none" content={line || " "} />
                    ))}
                  </box>
                )
              ) : (
                <EmptyState title="No persistent terminal" detail="Press Alt+N to create one" />
              )}
            </Panel>
            {showAudit && (
              <Panel title="MCP audit · manual input excluded" style={{ width: Math.max(30, Math.floor(width * 0.28)) }}>
                {!sessionsReady ? (
                  sessionsError ? <EmptyState title="Audit unavailable" detail="Terminal sessions could not be loaded" /> : <Loading label="Loading terminal activity" />
                ) : !selectedSession ? (
                  <EmptyState title="No terminal selected" detail="Create or select a terminal first" />
                ) : !outputReady ? (
                  selectedOutputError ? <EmptyState title="Audit unavailable" detail="Press Alt+R to try again" /> : <Loading label="Loading terminal activity" />
                ) : (
                  <AuditRail entries={audit} />
                )}
              </Panel>
            )}
          </box>
          <box style={{ height: 3, flexDirection: "row", gap: 1 }}>
            <Panel title="Command" active={Boolean(selectedSession)} accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, paddingLeft: 1, paddingRight: 1 }}>
              <input
                key={selectedSession?.session_id || "no-session"}
                ref={commandInputRef}
                focused={Boolean(selectedSession) && !rawMode && dialog.type === "none"}
                placeholder={!sessionsReady ? "Loading terminals…" : selectedSession ? "Enter a command…" : "Create a terminal first"}
                onSubmit={(value: unknown) => submitCommand(typeof value === "string" ? value : "")}
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
            {activeSessions.map((session, index) => (
              <box
                key={session.session_id}
                onMouseDown={() => selectSession(index)}
                style={{
                  height: 1,
                  marginRight: 1,
                  paddingLeft: 1,
                  paddingRight: 1,
                  backgroundColor: index === selected ? colors.selected : theme.panelAlt,
                }}
              >
                <text
                  fg={index === selected ? colors.accent : theme.muted}
                  attributes={index === selected ? 1 : 0}
                  content={session.session_id}
                />
              </box>
            ))}
            {!sessionsReady
              ? <text fg={sessionsError ? theme.red : theme.faint} content={sessionsError ? "Sessions unavailable" : "Loading sessions…"} />
              : activeSessions.length === 0 && <text fg={theme.faint} content="No sessions" />}
            <box style={{ flexGrow: 1 }} />
            {selectedSession?.created && (
              <text fg={theme.faint} content={formatAge(Number(selectedSession.created))} />
            )}
          </box>
        </box>
      </box>
      <KeyHint
        accent={colors.accent}
        items={[
          { key: "Alt+←", label: "previous", onPress: () => selectSession(selected - 1), disabled: standardFooterLocked || activeSessions.length < 2 },
          { key: "Alt+→", label: "next", onPress: () => selectSession(selected + 1), disabled: standardFooterLocked || activeSessions.length < 2 },
          { key: "Alt+N", label: "new", onPress: startTerminal, disabled: standardFooterLocked },
          { key: "Alt+W", label: "kill", onPress: killTerminal, disabled: standardFooterLocked || !selectedSession },
          { key: "Alt+A", label: "audit", onPress: toggleAudit, disabled: standardFooterLocked },
          { key: "PgUp", label: "older", onPress: () => scrollOutput(terminalRows), disabled: standardFooterLocked || !selectedSession || safeScrollOffset >= maxScrollOffset },
          { key: "PgDn", label: "newer", onPress: () => scrollOutput(-terminalRows), disabled: standardFooterLocked || !selectedSession || safeScrollOffset === 0 },
          { key: "F8", label: rawMode ? "leave raw" : "raw mode", onPress: toggleRawMode, disabled: footerLocked || !selectedSession },
          { key: "Alt+[", label: "prev machine", onPress: () => switchMachine(-1), disabled: standardFooterLocked || machines.length < 2 },
          { key: "Alt+]", label: "next machine", onPress: () => switchMachine(1), disabled: standardFooterLocked || machines.length < 2 },
          { key: "Alt+R", label: "refresh", onPress: () => void refreshOutput(true), disabled: standardFooterLocked || !selectedSession },
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
