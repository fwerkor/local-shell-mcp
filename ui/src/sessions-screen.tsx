import type { ScrollBoxRenderable, TextareaRenderable } from "@opentui/core"
import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useRef, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, Loading, Modal, Panel, formatAge, useVisibleRows } from "./components"
import { handleSelectionScroll } from "./mouse"
import { cyclePane, scrollPaneForKey } from "./pane-navigation"
import { clampIndex } from "./state-utils"
import { screenTheme, theme } from "./theme"
import type { LogicalSession, LogicalSessionsPayload } from "./types"

const colors = screenTheme.Sessions

type SessionPane = "list" | "details"
const SESSION_PANES = ["list", "details"] as const satisfies readonly SessionPane[]

type SessionDialog =
  | { type: "none" }
  | { type: "new" }
  | { type: "finish"; session: LogicalSession }
  | { type: "cancel"; session: LogicalSession }
  | { type: "delete"; session: LogicalSession }

function short(value: string | null | undefined, length: number): string {
  const normalized = String(value || "").replace(/\s+/g, " ").trim()
  return normalized.length > length ? `${normalized.slice(0, Math.max(1, length - 1))}…` : normalized
}

function sessionTitle(session: LogicalSession): string {
  return session.label || session.objective || session.session_id
}

function statusColor(status: string): string {
  if (status === "active" || status === "completed") return theme.green
  if (status === "cancelled" || status === "blocked") return theme.orange
  return theme.muted
}

function goalSummary(session: LogicalSession): string {
  if (!session.plan) return "No Goal"
  const done = session.plan.steps.filter((step) => step.status === "completed" || step.status === "skipped").length
  return `${session.plan.status} ${done}/${session.plan.steps.length}`
}

export function SessionsScreen({
  width,
  height,
  setStatus,
  keyboardEnabled,
  onInteractionLockChange,
}: {
  width: number
  height: number
  setStatus: (message: string) => void
  keyboardEnabled: boolean
  onInteractionLockChange: (locked: boolean) => void
}) {
  const [payload, setPayload] = useState<LogicalSessionsPayload>({ sessions: [], counts: { active: 0, completed: 0, cancelled: 0, stale: 0, total: 0 } })
  const [selected, setSelected] = useState(0)
  const [detail, setDetail] = useState<LogicalSession | null>(null)
  const [activePane, setActivePane] = useState<SessionPane>("list")
  const [dialog, setDialog] = useState<SessionDialog>({ type: "none" })
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const refreshController = useRef<AbortController | null>(null)
  const refreshRequest = useRef(0)
  const detailController = useRef<AbortController | null>(null)
  const detailRequest = useRef(0)
  const selectedIdRef = useRef<string | null>(null)
  const detailsScrollRef = useRef<ScrollBoxRenderable | null>(null)
  const promptRef = useRef<TextareaRenderable>(null)
  const sessions = payload.sessions
  const summary = sessions[selected]
  const current = detail?.session_id === summary?.session_id ? detail : summary
  selectedIdRef.current = summary?.session_id || null
  const compact = width < 92
  const visibleCount = Math.max(3, Math.floor((height - (compact ? 23 : 12)) / 2))
  const { rows, start } = useVisibleRows(sessions, selected, visibleCount)

  const loadDetail = useCallback(async (sessionId: string | null) => {
    detailController.current?.abort()
    const requestId = ++detailRequest.current
    if (!sessionId) {
      setDetail(null)
      return
    }
    const controller = new AbortController()
    detailController.current = controller
    try {
      const next = await api.sessionDetail(sessionId, controller.signal)
      if (!controller.signal.aborted && requestId === detailRequest.current) setDetail(next)
    } catch (error) {
      if (!controller.signal.aborted && requestId === detailRequest.current) setStatus(`Session detail: ${formatError(error)}`)
    } finally {
      if (detailController.current === controller) detailController.current = null
    }
  }, [setStatus])

  const refresh = useCallback(async (force = false) => {
    if (refreshController.current && !force) return
    refreshController.current?.abort()
    const controller = new AbortController()
    refreshController.current = controller
    const requestId = ++refreshRequest.current
    setLoading(true)
    try {
      const next = await api.sessions(controller.signal)
      if (controller.signal.aborted || requestId !== refreshRequest.current) return
      const selectedId = selectedIdRef.current
      setPayload(next)
      setSelected((value) => {
        const byId = selectedId ? next.sessions.findIndex((session) => session.session_id === selectedId) : -1
        return byId >= 0 ? byId : clampIndex(value, next.sessions.length)
      })
      setLoaded(true)
      setStatus(`${next.counts.active || 0} active logic session(s) · ${next.counts.total || next.sessions.length} total`)
    } catch (error) {
      if (!controller.signal.aborted && requestId === refreshRequest.current) {
        setStatus(`Sessions: ${formatError(error)}`)
      }
    } finally {
      if (refreshController.current === controller) refreshController.current = null
      if (requestId === refreshRequest.current) setLoading(false)
    }
  }, [setStatus])

  useEffect(() => {
    refreshRequest.current += 1
    void refresh()
    const timer = setInterval(() => void refresh(), 4_000)
    return () => {
      refreshRequest.current += 1
      refreshController.current?.abort()
      refreshController.current = null
      detailController.current?.abort()
      detailController.current = null
      clearInterval(timer)
    }
  }, [refresh])

  useEffect(() => {
    detailsScrollRef.current?.scrollTo(0)
    void loadDetail(summary?.session_id || null)
  }, [loadDetail, summary?.session_id])

  useEffect(() => {
    onInteractionLockChange(dialog.type !== "none")
    return () => onInteractionLockChange(false)
  }, [dialog.type, onInteractionLockChange])

  const cycleActivePane = (delta = 1) => setActivePane((pane) => cyclePane(SESSION_PANES, pane, delta))
  const moveOrScroll = (key: { name: string; shift?: boolean }) => {
    if (activePane === "details") return scrollPaneForKey(detailsScrollRef.current, key)
    if (key.name === "j" || key.name === "down") {
      setSelected((value) => clampIndex(value + 1, sessions.length))
      return true
    }
    if (key.name === "k" || key.name === "up") {
      setSelected((value) => clampIndex(value - 1, sessions.length))
      return true
    }
    return false
  }

  const createSession = async () => {
    const prompt = promptRef.current?.plainText.trim() || ""
    try {
      const created = await api.sessionAction<LogicalSession>("start", {
        prompt: prompt || undefined,
      })
      selectedIdRef.current = created.session_id
      setDialog({ type: "none" })
      await refresh(true)
      await loadDetail(created.session_id)
      setStatus(`Created ${created.session_id}`)
    } catch (error) {
      setStatus(`Create session: ${formatError(error)}`)
    }
  }

  const lifecycle = async (action: "finish" | "cancel" | "delete", session: LogicalSession) => {
    try {
      await api.sessionAction(action, { session_id: session.session_id })
      setDialog({ type: "none" })
      if (action === "delete") selectedIdRef.current = null
      await refresh(true)
      if (action !== "delete") await loadDetail(session.session_id)
      setStatus(`${action === "finish" ? "Finished" : action === "cancel" ? "Cancelled" : "Deleted"} ${session.session_id}`)
    } catch (error) {
      setStatus(`${action}: ${formatError(error)}`)
    }
  }

  const activePlan = current?.plan && ["active", "blocked"].includes(current.plan.status)
  const footerLocked = !keyboardEnabled || dialog.type !== "none"

  useKeyboard((key) => {
    if (!keyboardEnabled) return
    if (dialog.type === "new") {
      if (key.name === "escape") setDialog({ type: "none" })
      else if (key.ctrl && key.name === "return") void createSession()
      return
    }
    if (dialog.type === "finish" || dialog.type === "cancel" || dialog.type === "delete") {
      if (key.name === "escape" || key.name === "n") setDialog({ type: "none" })
      else if (key.name === "y" || key.name === "return") void lifecycle(dialog.type, dialog.session)
      return
    }
    if (key.ctrl || key.option || key.meta) return
    if (key.name === "tab") {
      key.preventDefault()
      cycleActivePane(key.shift ? -1 : 1)
    } else if (key.name === "left") cycleActivePane(-1)
    else if (key.name === "right") cycleActivePane(1)
    else if (moveOrScroll(key)) return
    else if (key.name === "n") setDialog({ type: "new" })
    else if (key.name === "f" && current && current.status === "active" && !activePlan) setDialog({ type: "finish", session: current })
    else if (key.name === "c" && current && current.status === "active") setDialog({ type: "cancel", session: current })
    else if (key.name === "d" && current && current.status !== "active") setDialog({ type: "delete", session: current })
    else if (key.name === "r") void refresh(true)
  })

  const details = current ? (
    <scrollbox
      ref={detailsScrollRef}
      focused={false}
      style={{ flexGrow: 1 }}
      scrollY
      verticalScrollbarOptions={{ visible: true }}
    >
      <text fg={colors.accent} attributes={1} content={sessionTitle(current)} />
      <text fg={theme.faint} content={`ID        ${current.session_id}`} />
      <text fg={statusColor(current.status)} content={`Status    ${current.status}`} />
      <text fg={theme.faint} content={`Updated   ${formatAge(current.updated_at)}`} />
      <text fg={theme.borderBright} content="\nPrompt / objective" />
      <text fg={theme.muted} content={current.objective || "—"} />
      <text fg={theme.borderBright} content="\nProgress" />
      <text fg={theme.faint} content={`Summary   ${current.progress.summary || "—"}`} />
      <text fg={theme.faint} content={`Next      ${current.progress.next || "—"}`} />
      {current.progress.blockers.length > 0 && <text fg={theme.orange} content={`Blockers  ${current.progress.blockers.join(" · ")}`} />}
      {current.progress.findings.length > 0 && <text fg={theme.muted} content={`Findings  ${current.progress.findings.join(" · ")}`} />}
      <text fg={theme.borderBright} content="\nGoal" />
      {current.plan ? (
        <>
          <text fg={statusColor(current.plan.status)} attributes={1} content={goalSummary(current)} />
          {current.plan.note && <text fg={theme.faint} content={current.plan.note} />}
          {current.plan.steps.map((step) => (
            <text
              key={step.id}
              fg={statusColor(step.status)}
              content={`${step.status === "completed" ? "✓" : step.status === "active" ? "▶" : step.status === "skipped" ? "–" : "○"} ${step.text}${step.note ? ` — ${step.note}` : ""}`}
            />
          ))}
        </>
      ) : (
        <text fg={theme.faint} content="No Goal attached" />
      )}
      <text fg={theme.borderBright} content="\nRecent activity" />
      {[...current.recent_activity].reverse().slice(0, 14).map((event) => (
        <box key={`${event.seq}-${event.type}`} style={{ flexDirection: "column", marginBottom: 1 }}>
          <text fg={theme.muted} content={`${event.type.replace("session.", "")} · ${event.actor} · ${formatAge(event.ts)}`} />
          {typeof event.data?.summary === "string" && <text fg={theme.faint} content={short(event.data.summary, Math.max(24, width - 18))} />}
        </box>
      ))}
      {current.recent_activity.length === 0 && <text fg={theme.faint} content="No recorded activity" />}
    </scrollbox>
  ) : !loaded ? (
    loading ? <Loading label="Loading session details" /> : <EmptyState title="Sessions unavailable" detail="Press r to try again" />
  ) : (
    <EmptyState title="No session selected" detail="Press n to create one" />
  )

  return (
    <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
      <box style={{ height: width < 70 ? 2 : 4, flexDirection: "row", gap: 1 }}>
        <Panel title="Active" active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.green} attributes={1} content={loaded ? String(payload.counts.active || 0) : "—"} />
        </Panel>
        <Panel title="Done" style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.green} attributes={1} content={loaded ? String(payload.counts.completed || 0) : "—"} />
        </Panel>
        <Panel title="Cancelled" style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.orange} attributes={1} content={loaded ? String(payload.counts.cancelled || 0) : "—"} />
        </Panel>
        <Panel title="Stale" style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.muted} attributes={1} content={loaded ? String(payload.counts.stale || 0) : "—"} />
        </Panel>
        <Panel title="Total" style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={colors.accent} attributes={1} content={loaded ? String(payload.counts.total ?? sessions.length) : "—"} />
        </Panel>
      </box>
      <box style={{ flexGrow: 1, minHeight: 0, flexDirection: compact ? "column" : "row", gap: 1 }}>
        <Panel
          title="Logic sessions"
          active={activePane === "list"}
          accent={colors.accent}
          activeBackground={colors.panel}
          onMouseDown={() => setActivePane("list")}
          style={{ width: compact ? "100%" : "52%", height: compact ? "44%" : "100%", minHeight: 0, paddingTop: 1, overflow: "hidden" }}
        >
          {!loaded ? (
            loading ? <Loading label="Loading logic sessions" /> : <EmptyState title="Sessions unavailable" detail="Press r to try again" />
          ) : sessions.length === 0 ? (
            <EmptyState title="No logic sessions" detail="Press n to create one, or let an agent start one" />
          ) : (
            <box
              onMouseScroll={(event) => handleSelectionScroll(event, (delta) => setSelected((value) => clampIndex(value + delta, sessions.length)))}
              style={{ flexDirection: "column", flexGrow: 1 }}
            >
              <box style={{ height: 2, flexDirection: "row", paddingLeft: 1 }}>
                <text fg={theme.faint} content={width < 70 ? "STATE  SESSION" : "STATE       SESSION                              GOAL"} />
              </box>
              {rows.map((session, offset) => {
                const index = start + offset
                const active = index === selected
                return (
                  <box
                    key={session.session_id}
                    onMouseDown={() => setSelected(index)}
                    style={{ height: 2, flexDirection: "row", alignItems: "center", paddingLeft: 1, paddingRight: 1, backgroundColor: active ? colors.selected : index % 2 ? theme.panelAlt : undefined }}
                  >
                    <text fg={statusColor(session.status)} attributes={1} content={`${session.status === "active" ? "●" : session.status === "completed" ? "✓" : session.status === "stale" ? "·" : "×"} ${session.status.slice(0, 7).padEnd(8)} `} />
                    <text fg={active ? theme.text : theme.muted} attributes={active ? 1 : 0} content={short(sessionTitle(session), compact ? Math.max(18, width - 22) : 34).padEnd(compact ? 1 : 36)} />
                    {!compact && <text fg={session.plan ? colors.accent : theme.faint} content={short(goalSummary(session), 16)} />}
                  </box>
                )
              })}
            </box>
          )}
        </Panel>
        <Panel
          title="Session details"
          active={activePane === "details"}
          accent={colors.accent}
          activeBackground={colors.panel}
          onMouseDown={() => setActivePane("details")}
          style={{ flexGrow: 1, width: compact ? "100%" : "48%", minHeight: 0, padding: 1 }}
        >
          {details}
        </Panel>
      </box>
      <KeyHint
        accent={colors.accent}
        items={[
          { key: "Tab", label: "pane", onPress: () => cycleActivePane(1), disabled: footerLocked },
          { key: "j", label: activePane === "details" ? "scroll" : "down", onPress: () => moveOrScroll({ name: "j" }), disabled: footerLocked || (activePane === "list" && sessions.length === 0) },
          { key: "k", label: activePane === "details" ? "scroll" : "up", onPress: () => moveOrScroll({ name: "k" }), disabled: footerLocked || (activePane === "list" && sessions.length === 0) },
          { key: "n", label: "new", onPress: () => setDialog({ type: "new" }), disabled: footerLocked },
          { key: "f", label: "finish", onPress: () => current && setDialog({ type: "finish", session: current }), disabled: footerLocked || !current || current.status !== "active" || Boolean(activePlan) },
          { key: "c", label: "cancel", onPress: () => current && setDialog({ type: "cancel", session: current }), disabled: footerLocked || !current || current.status !== "active" },
          { key: "d", label: "delete", onPress: () => current && setDialog({ type: "delete", session: current }), disabled: footerLocked || !current || current.status === "active" },
          { key: "r", label: "refresh", onPress: () => void refresh(true), disabled: footerLocked || loading },
        ]}
      />
      {dialog.type === "new" && (
        <Modal title="New logic session" width={Math.max(42, Math.min(100, width - 6))} height={Math.max(14, Math.min(24, height - 6))}>
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.muted} content="Prompt (optional) · saved as the session objective" />
          <textarea
            ref={promptRef}
            focused
            initialValue=""
            style={{ flexGrow: 1, backgroundColor: theme.bg, textColor: theme.text }}
          />
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.faint} content="Handoff stays explicit: give the resulting session_id to the next agent." />
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.faint} content="Ctrl+Enter create · Esc cancel" />
        </Modal>
      )}
      {(dialog.type === "finish" || dialog.type === "cancel" || dialog.type === "delete") && (
        <Modal title={`${dialog.type === "finish" ? "Finish" : dialog.type === "cancel" ? "Cancel" : "Delete"} session`} height={9}>
          <text style={{ height: 1, flexShrink: 0 }} fg={dialog.type === "finish" ? theme.green : theme.red} attributes={1} content={sessionTitle(dialog.session)} />
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.muted} content={dialog.type === "delete" ? "Durable progress and activity history will be permanently removed." : dialog.type === "cancel" ? "The session and unfinished Goal state will be cancelled." : "The durable task will be marked completed."} />
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.faint} content="y / Enter confirm · n / Esc cancel" />
        </Modal>
      )}
    </box>
  )
}
