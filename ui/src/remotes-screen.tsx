import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useRef, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, Loading, Modal, Panel, formatAge, useVisibleRows } from "./components"
import { handleSelectionScroll } from "./mouse"
import { remoteSystemInfo, remoteVersion } from "./remotes-utils"
import { clampIndex } from "./state-utils"
import { screenTheme, theme } from "./theme"
import type { InvitePayload, Machine } from "./types"

const colors = screenTheme.Remotes

type RemoteDialog =
  | { type: "none" }
  | { type: "invite" }
  | { type: "invite-result"; invite: InvitePayload }
  | { type: "rename"; machine: Machine }
  | { type: "revoke"; machine: Machine }

export function RemoteInviteResultDialog({ invite, width }: { invite: InvitePayload; width: number }) {
  return (
    <Modal title="Remote join command" width={Math.max(38, Math.min(88, width - 6))} height={15}>
      <text style={{ height: 1, flexShrink: 0 }} fg={theme.green} attributes={1} content="Invite ready" />
      <text style={{ height: 1, flexShrink: 0 }} fg={theme.muted} content="Run this command on the remote node:" />
      <box
        style={{
          flexGrow: 1,
          minHeight: 4,
          border: true,
          borderColor: theme.borderBright,
          backgroundColor: theme.bg,
          paddingLeft: 1,
          paddingRight: 1,
        }}
      >
        <text style={{ flexShrink: 0 }} fg={colors.accent} content={invite.command} />
      </box>
      <text
        style={{ height: 1, flexShrink: 0 }}
        fg={theme.faint}
        content={`Expires ${new Date(invite.expires_at * 1000).toLocaleTimeString()} · Enter/Esc close`}
      />
    </Modal>
  )
}

export function RemotesScreen({
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
  const [machines, setMachines] = useState<Machine[]>([])
  const [enabled, setEnabled] = useState(true)
  const [selected, setSelected] = useState(0)
  const [dialog, setDialog] = useState<RemoteDialog>({ type: "none" })
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const refreshRequest = useRef(0)
  const refreshController = useRef<AbortController | null>(null)
  const current = machines[selected]
  const compact = width < 92
  const { rows, start } = useVisibleRows(machines, selected, Math.max(5, height - (compact ? 21 : 13)))

  const refresh = useCallback(async (force = false) => {
    if (refreshController.current && !force) return
    refreshController.current?.abort()
    const controller = new AbortController()
    refreshController.current = controller
    const requestId = ++refreshRequest.current
    setLoading(true)
    try {
      const payload = await api.remotes(controller.signal)
      if (requestId !== refreshRequest.current || controller.signal.aborted) return
      setMachines(payload.machines)
      setEnabled(payload.enabled !== false)
      setSelected((value) => clampIndex(value, payload.machines.length))
      setLoaded(true)
      setStatus(
        payload.enabled === false
          ? "Remote worker support is disabled"
          : `${payload.counts.online || 0} remote node(s) online`,
      )
    } catch (error) {
      if (requestId === refreshRequest.current && !controller.signal.aborted) {
        setStatus(`Remotes: ${formatError(error)}`)
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
      clearInterval(timer)
    }
  }, [refresh])

  useEffect(() => {
    onInteractionLockChange(dialog.type !== "none")
    return () => onInteractionLockChange(false)
  }, [dialog.type, onInteractionLockChange])

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
      await refresh(true)
    } catch (error) {
      setStatus(`Rename: ${formatError(error)}`)
    }
  }

  const moveSelection = (delta: number) => {
    setSelected((value) => clampIndex(value + delta, machines.length))
  }
  const createRemoteInvite = () => enabled && setDialog({ type: "invite" })
  const renameCurrent = () => current && enabled && setDialog({ type: "rename", machine: current })
  const revokeCurrent = () => current && enabled && setDialog({ type: "revoke", machine: current })
  const footerLocked = !keyboardEnabled || dialog.type !== "none"

  useKeyboard((key) => {
    if (!keyboardEnabled) return
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
            await refresh(true)
          })
          .catch((error) => setStatus(`Revoke: ${formatError(error)}`))
      }
      return
    }
    if (key.name === "j" || key.name === "down") moveSelection(1)
    else if (key.name === "k" || key.name === "up") moveSelection(-1)
    else if (key.name === "n") createRemoteInvite()
    else if (key.name === "e") renameCurrent()
    else if (key.name === "d") revokeCurrent()
    else if (key.name === "r") void refresh(true)
  })

  const online = machines.filter((machine) => machine.status === "online").length
  const offline = machines.length - online

  return (
    <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
      {width < 70 ? (
        <Panel title="Remote status" active accent={colors.accent} activeBackground={colors.panel} style={{ height: 3, alignItems: "center", justifyContent: "center" }}>
          <text
            fg={theme.muted}
            content={loaded
              ? `On ${online}  │  Off ${offline}  │  Total ${machines.length}  │  ${loading ? "SYNC" : "READY"}`
              : `On —  │  Off —  │  Total —  │  ${loading ? "SYNC" : "ERROR"}`}
          />
        </Panel>
      ) : (
        <box style={{ height: compact ? 2 : 4, flexDirection: "row", gap: 1 }}>
          <Panel title={compact ? "On" : "Online"} active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
            <text fg={theme.green} attributes={1} content={loaded ? String(online) : "—"} />
          </Panel>
          <Panel title={compact ? "Off" : "Offline"} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
            <text fg={offline ? theme.orange : theme.faint} attributes={1} content={loaded ? String(offline) : "—"} />
          </Panel>
          <Panel title="Total" style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
            <text fg={colors.accent} attributes={1} content={loaded ? String(machines.length) : "—"} />
          </Panel>
          <Panel title={compact ? "Ctl" : "Controller"} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
            <text fg={theme.blue} content={loading ? (compact ? "SYNC" : "SYNCING") : loaded ? "READY" : "ERROR"} />
          </Panel>
        </box>
      )}
      <box style={{ flexGrow: 1, flexDirection: compact ? "column" : "row", gap: 1 }}>
        <Panel title="Remote nodes" active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, paddingTop: 1 }}>
          {!loaded ? (
            loading ? <Loading label="Loading remote nodes" /> : <EmptyState title="Remotes unavailable" detail="Press r to try again" />
          ) : machines.length === 0 ? (
            <EmptyState
              title={enabled ? "No remote nodes" : "Remote workers disabled"}
              detail={enabled ? "Press n to create a one-time join invite" : "Enable remote workers in server configuration"}
            />
          ) : (
            <box
              onMouseScroll={(event) => handleSelectionScroll(
                event,
                (delta) => setSelected((value) => clampIndex(value + delta, machines.length)),
              )}
              style={{ flexDirection: "column", flexGrow: 1 }}
            >
              <box style={{ height: 2, flexDirection: "row", paddingLeft: 1 }}>
                <text
                  fg={theme.faint}
                  content={compact ? "STATE  NAME" : "STATE  NAME                    VERSION     WORKDIR"}
                />
              </box>
              {rows.map((machine, offset) => {
                const index = start + offset
                const active = index === selected
                const onlineNode = machine.status === "online"
                return (
                  <box
                    key={machine.name}
                    onMouseDown={() => setSelected(index)}
                    style={{
                      height: 2,
                      flexDirection: "row",
                      alignItems: "center",
                      paddingLeft: 1,
                      paddingRight: 1,
                      backgroundColor: active ? colors.selected : index % 2 ? theme.panelAlt : undefined,
                    }}
                  >
                    <text fg={onlineNode ? theme.green : theme.faint} attributes={1} content={onlineNode ? "● ON   " : "○ OFF  "} />
                    <text
                      fg={active ? theme.text : theme.muted}
                      attributes={active ? 1 : 0}
                      content={compact ? machine.name : machine.name.slice(0, 23).padEnd(24)}
                    />
                    {!compact && <text fg={theme.blue} content={remoteVersion(machine).slice(0, 11).padEnd(12)} />}
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
            height: compact ? 11 : "100%",
            padding: 1,
          }}
        >
          {current ? (
            <scrollbox
              focused={false}
              style={{ flexGrow: 1 }}
              scrollY
              verticalScrollbarOptions={{ visible: true }}
            >
              <text fg={current.status === "online" ? theme.green : theme.orange} attributes={1} content={current.name} />
              <text fg={theme.faint} content={`Status       ${current.status}`} />
              <text fg={theme.faint} content={`LSM version  ${remoteVersion(current)}`} />
              <text fg={theme.faint} content={`Last seen    ${formatAge(current.last_seen)}`} />
              <text fg={theme.faint} content={`Workdir      ${current.workdir || "—"}`} />
              <text fg={theme.faint} content={`Capabilities ${(current.capabilities || []).join(", ") || "—"}`} />
              <text fg={theme.borderBright} content="\nSystem information" />
              <text fg={theme.muted} content={JSON.stringify(remoteSystemInfo(current), null, 2)} />
            </scrollbox>
          ) : !loaded ? (
            loading ? <Loading label="Loading node details" /> : <EmptyState title="Remotes unavailable" detail="Press r to try again" />
          ) : (
            <EmptyState title="No node selected" detail="Create an invite to attach one" />
          )}
        </Panel>
      </box>
      <KeyHint
        accent={colors.accent}
        items={[
          { key: "j", label: "down", onPress: () => moveSelection(1), disabled: footerLocked || machines.length === 0 },
          { key: "k", label: "up", onPress: () => moveSelection(-1), disabled: footerLocked || machines.length === 0 },
          { key: "n", label: "new invite", onPress: createRemoteInvite, disabled: footerLocked || !enabled },
          { key: "e", label: "rename", onPress: renameCurrent, disabled: footerLocked || !enabled || !current },
          { key: "d", label: "revoke", onPress: revokeCurrent, disabled: footerLocked || !enabled || !current },
          { key: "r", label: "refresh", onPress: () => void refresh(true), disabled: footerLocked || loading },
        ]}
      />
      {dialog.type === "invite" && (
        <Modal title="Create remote invite" height={9}>
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.muted} content="Enter: optional-name [optional-workdir]" />
          <box style={{ height: 3, flexShrink: 0, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused placeholder="build-host /workspace" onSubmit={(value: unknown) => void createInvite(typeof value === "string" ? value : "")} />
          </box>
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.faint} content="Invite expires automatically · Enter create · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "invite-result" && (
        <RemoteInviteResultDialog invite={dialog.invite} width={width} />
      )}
      {dialog.type === "rename" && (
        <Modal title="Rename remote" height={9}>
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.muted} content={`Current name: ${dialog.machine.name}`} />
          <box style={{ height: 3, flexShrink: 0, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused value={dialog.machine.name} onSubmit={(value: unknown) => void rename(typeof value === "string" ? value : "")} />
          </box>
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.faint} content="Enter save · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "revoke" && (
        <Modal title="Revoke remote" height={8}>
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.red} attributes={1} content={`Revoke ${dialog.machine.name}?`} />
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.muted} content="Its persistent identity will no longer reconnect." />
          <text style={{ height: 1, flexShrink: 0 }} fg={theme.faint} content="y / Enter confirm · n / Esc cancel" />
        </Modal>
      )}
    </box>
  )
}
