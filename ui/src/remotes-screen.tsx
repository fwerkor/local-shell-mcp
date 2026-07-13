import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useRef, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, Modal, Panel, formatAge, useVisibleRows } from "./components"
import { theme } from "./theme"
import type { InvitePayload, Machine } from "./types"

type RemoteDialog =
  | { type: "none" }
  | { type: "invite" }
  | { type: "invite-result"; invite: InvitePayload }
  | { type: "rename"; machine: Machine }
  | { type: "revoke"; machine: Machine }

export function RemotesScreen({
  width,
  height,
  setStatus,
}: {
  width: number
  height: number
  setStatus: (message: string) => void
}) {
  const [machines, setMachines] = useState<Machine[]>([])
  const [enabled, setEnabled] = useState(true)
  const [selected, setSelected] = useState(0)
  const [dialog, setDialog] = useState<RemoteDialog>({ type: "none" })
  const [loading, setLoading] = useState(false)
  const refreshRequest = useRef(0)
  const current = machines[selected]
  const compact = width < 92
  const { rows, start } = useVisibleRows(machines, selected, Math.max(5, height - (compact ? 20 : 13)))

  const refresh = useCallback(async () => {
    const requestId = ++refreshRequest.current
    setLoading(true)
    try {
      const payload = await api.remotes()
      if (requestId !== refreshRequest.current) return
      setMachines(payload.machines)
      setEnabled(payload.enabled !== false)
      setSelected((value) => Math.min(value, Math.max(0, payload.machines.length - 1)))
      setStatus(
        payload.enabled === false
          ? "Remote worker support is disabled"
          : `${payload.counts.online || 0} remote node(s) online`,
      )
    } catch (error) {
      if (requestId === refreshRequest.current) setStatus(`Remotes: ${formatError(error)}`)
    } finally {
      if (requestId === refreshRequest.current) setLoading(false)
    }
  }, [setStatus])

  useEffect(() => {
    refreshRequest.current += 1
    void refresh()
    const timer = setInterval(() => void refresh(), 4_000)
    return () => {
      refreshRequest.current += 1
      clearInterval(timer)
    }
  }, [refresh])

  const createInvite = async (value: string) => {
    const [name, ...workdirParts] = value.trim().split(/\s+/)
    try {
      const invite = await api.invite({
        name: name || undefined,
        workdir: workdirParts.join(" ") || undefined,
      })
      setDialog({ type: "invite-result", invite })
    } catch (error) {
      setStatus(`Invite: ${formatError(error)}`)
    }
  }

  const rename = async (newName: string) => {
    if (dialog.type !== "rename") return
    try {
      await api.remoteAction("rename", { machine: dialog.machine.name, new_name: newName.trim() })
      setDialog({ type: "none" })
      await refresh()
    } catch (error) {
      setStatus(`Rename: ${formatError(error)}`)
    }
  }

  useKeyboard((key) => {
    if (dialog.type === "invite" || dialog.type === "rename") {
      if (key.name === "escape") setDialog({ type: "none" })
      return
    }
    if (dialog.type === "invite-result") {
      if (key.name === "escape" || key.name === "return") setDialog({ type: "none" })
      return
    }
    if (dialog.type === "revoke") {
      if (key.name === "escape" || key.name === "n") setDialog({ type: "none" })
      if (key.name === "y" || key.name === "return") {
        void api
          .remoteAction("revoke", { machine: dialog.machine.name })
          .then(async () => {
            setDialog({ type: "none" })
            await refresh()
          })
          .catch((error) => setStatus(`Revoke: ${formatError(error)}`))
      }
      return
    }
    if (key.name === "j" || key.name === "down") setSelected((value) => Math.min(machines.length - 1, value + 1))
    else if (key.name === "k" || key.name === "up") setSelected((value) => Math.max(0, value - 1))
    else if (key.name === "n" && enabled) setDialog({ type: "invite" })
    else if (key.name === "e" && current && enabled) setDialog({ type: "rename", machine: current })
    else if (key.name === "d" && current && enabled) setDialog({ type: "revoke", machine: current })
    else if (key.name === "r") void refresh()
  })

  const online = machines.filter((machine) => machine.status === "online").length
  const offline = machines.length - online

  return (
    <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
      <box style={{ height: compact ? 2 : 4, flexDirection: "row", gap: 1 }}>
        <Panel title={compact ? "On" : "Online"} active style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.green} attributes={1} content={String(online)} />
        </Panel>
        <Panel title={compact ? "Off" : "Offline"} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={offline ? theme.orange : theme.faint} attributes={1} content={String(offline)} />
        </Panel>
        <Panel title="Total" style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.cyan} attributes={1} content={String(machines.length)} />
        </Panel>
        <Panel title={compact ? "Ctl" : "Controller"} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.blue} content={loading ? (compact ? "SYNC" : "SYNCING") : "READY"} />
        </Panel>
      </box>
      <box style={{ flexGrow: 1, flexDirection: compact ? "column" : "row", gap: 1 }}>
        <Panel title="Remote nodes" active style={{ flexGrow: 1, paddingTop: 1 }}>
          {machines.length === 0 ? (
            <EmptyState
              title={enabled ? "No remote nodes" : "Remote workers disabled"}
              detail={enabled ? "Press n to create a one-time join invite" : "Enable remote workers in server configuration"}
            />
          ) : (
            <box style={{ flexDirection: "column", flexGrow: 1 }}>
              <box style={{ height: 2, flexDirection: "row", paddingLeft: 1 }}>
                <text fg={theme.faint} content={compact ? "STATE  NAME" : "STATE  NAME                         WORKDIR"} />
              </box>
              {rows.map((machine, offset) => {
                const index = start + offset
                const active = index === selected
                const onlineNode = machine.status === "online"
                return (
                  <box
                    key={machine.name}
                    style={{
                      height: 2,
                      flexDirection: "row",
                      alignItems: "center",
                      paddingLeft: 1,
                      paddingRight: 1,
                      backgroundColor: active ? theme.selectedStrong : index % 2 ? theme.panelAlt : undefined,
                    }}
                  >
                    <text fg={onlineNode ? theme.green : theme.faint} attributes={1} content={onlineNode ? "● ON   " : "○ OFF  "} />
                    <text
                      fg={active ? theme.text : theme.muted}
                      attributes={active ? 1 : 0}
                      content={compact ? machine.name : machine.name.padEnd(29)}
                    />
                    {!compact && <text fg={theme.faint} content={machine.workdir || "—"} />}
                  </box>
                )
              })}
            </box>
          )}
        </Panel>
        <Panel
          title="Node details"
          style={{
            width: compact ? "100%" : "34%",
            height: compact ? 10 : "100%",
            padding: 1,
          }}
        >
          {current ? (
            <box style={{ flexDirection: "column" }}>
              <text fg={current.status === "online" ? theme.green : theme.orange} attributes={1} content={current.name} />
              <text fg={theme.faint} content={`Status       ${current.status}`} />
              <text fg={theme.faint} content={`Last seen    ${formatAge(current.last_seen)}`} />
              <text fg={theme.faint} content={`Workdir      ${current.workdir || "—"}`} />
              <text fg={theme.faint} content={`Capabilities ${(current.capabilities || []).join(", ") || "—"}`} />
              <text fg={theme.borderBright} content="\nSystem information" />
              <text fg={theme.muted} content={JSON.stringify(current.info || {}, null, 2)} />
            </box>
          ) : (
            <EmptyState title="No node selected" detail="Create an invite to attach one" />
          )}
        </Panel>
      </box>
      <KeyHint items={[["j/k", "move"], ["n", "new invite"], ["e", "rename"], ["d", "revoke"], ["r", "refresh"]]} />
      {dialog.type === "invite" && (
        <Modal title="Create remote invite" height={8}>
          <text fg={theme.muted} content="Enter: optional-name [optional-workdir]" />
          <box style={{ height: 3, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused placeholder="build-host /workspace" onSubmit={(value: unknown) => void createInvite(typeof value === "string" ? value : "")} />
          </box>
          <text fg={theme.faint} content="Invite expires automatically · Enter create · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "invite-result" && (
        <Modal title="Remote join command" width={Math.max(38, Math.min(88, width - 6))} height={12}>
          <text fg={theme.green} attributes={1} content="Invite ready" />
          <text fg={theme.muted} content="Run this command on the remote node:" />
          <box style={{ flexGrow: 1, border: true, borderColor: theme.borderBright, backgroundColor: theme.bg, padding: 1 }}>
            <text fg={theme.cyan} content={dialog.invite.command} />
          </box>
          <text fg={theme.faint} content={`Expires ${new Date(dialog.invite.expires_at * 1000).toLocaleTimeString()} · Enter/Esc close`} />
        </Modal>
      )}
      {dialog.type === "rename" && (
        <Modal title="Rename remote" height={7}>
          <text fg={theme.muted} content={`Current name: ${dialog.machine.name}`} />
          <box style={{ height: 3, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused value={dialog.machine.name} onSubmit={(value: unknown) => void rename(typeof value === "string" ? value : "")} />
          </box>
          <text fg={theme.faint} content="Enter save · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "revoke" && (
        <Modal title="Revoke remote" height={7}>
          <text fg={theme.red} attributes={1} content={`Revoke ${dialog.machine.name}?`} />
          <text fg={theme.muted} content="Its persistent identity will no longer reconnect." />
          <text fg={theme.faint} content="y / Enter confirm · n / Esc cancel" />
        </Modal>
      )}
    </box>
  )
}
