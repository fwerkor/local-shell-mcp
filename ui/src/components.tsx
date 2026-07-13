import type { ReactNode } from "react"
import { useMemo } from "react"
import type { Machine, ScreenName } from "./types"
import { theme } from "./theme"

export const SCREENS: ScreenName[] = ["Files", "Terminals", "Todos", "Audit", "Remotes"]

export function TopNav({
  active,
  width,
  onSelect,
}: {
  active: ScreenName
  width: number
  onSelect: (screen: ScreenName) => void
}) {
  const compact = width < 88
  return (
    <box
      style={{
        height: 3,
        flexDirection: "row",
        alignItems: "center",
        paddingLeft: 1,
        paddingRight: 1,
        border: true,
        borderStyle: "rounded",
        borderColor: theme.borderBright,
        backgroundColor: theme.panelAlt,
      }}
    >
      <text fg={theme.cyan} attributes={1} content={compact ? "LSM" : "LOCAL SHELL MCP"} />
      <text fg={theme.faint} content="  /  " />
      {SCREENS.map((screen, index) => {
        const selected = screen === active
        const key = `A${index + 1}`
        const label = compact ? `${key}:${screen.slice(0, 3)}` : `Alt+${index + 1} ${screen}`
        return (
          <box
            key={screen}
            onMouseDown={() => onSelect(screen)}
            style={{
              height: 1,
              marginRight: compact ? 1 : 2,
              paddingLeft: 1,
              paddingRight: 1,
              backgroundColor: selected ? theme.selectedStrong : undefined,
            }}
          >
            <text fg={selected ? theme.cyan : theme.muted} attributes={selected ? 1 : 0} content={label} />
          </box>
        )
      })}
      <box style={{ flexGrow: 1 }} />
      {!compact && <text fg={theme.faint} content="Alt+1…5 switch · F1 help · Ctrl+Q quit" />}
    </box>
  )
}

export function MachineSidebar({
  machines,
  selected,
  title = "Machines",
  width = 23,
}: {
  machines: Machine[]
  selected: string
  title?: string
  width?: number
}) {
  return (
    <box
      title={` ${title} `}
      style={{
        width,
        flexShrink: 0,
        flexDirection: "column",
        border: true,
        borderStyle: "rounded",
        borderColor: theme.border,
        backgroundColor: theme.panel,
        paddingTop: 1,
      }}
    >
      {machines.map((machine) => {
        const active = machine.name === selected
        const online = machine.status === "online"
        return (
          <box
            key={machine.name}
            style={{
              height: 2,
              paddingLeft: 1,
              paddingRight: 1,
              flexDirection: "row",
              backgroundColor: active ? theme.selected : undefined,
            }}
          >
            <text fg={online ? theme.green : theme.faint} content={online ? "● " : "○ "} />
            <text fg={active ? theme.text : theme.muted} attributes={active ? 1 : 0} content={machine.name} />
          </box>
        )
      })}
      {machines.length === 0 && <text fg={theme.faint} content="  No machines" />}
      <box style={{ flexGrow: 1 }} />
      <text fg={theme.faint} content="  [ / ] machine" />
    </box>
  )
}

export function Panel({
  title,
  active = false,
  children,
  style,
}: {
  title: string
  active?: boolean
  children?: ReactNode
  style?: Record<string, unknown>
}) {
  return (
    <box
      title={` ${title} `}
      style={{
        flexDirection: "column",
        border: true,
        borderStyle: "rounded",
        borderColor: active ? theme.cyan : theme.border,
        backgroundColor: active ? theme.panelAlt : theme.panel,
        ...style,
      }}
    >
      {children}
    </box>
  )
}

export function KeyHint({ items }: { items: Array<[string, string]> }) {
  return (
    <box
      style={{
        height: 2,
        flexDirection: "row",
        alignItems: "center",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: theme.panelAlt,
      }}
    >
      {items.map(([key, label], index) => (
        <box key={`${key}-${label}`} style={{ flexDirection: "row", marginRight: 2 }}>
          <text fg={theme.cyan} attributes={1} content={key} />
          <text fg={theme.muted} content={` ${label}${index === items.length - 1 ? "" : ""}`} />
        </box>
      ))}
    </box>
  )
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <box style={{ flexGrow: 1, alignItems: "center", justifyContent: "center", flexDirection: "column" }}>
      <text fg={theme.muted} attributes={1} content={title} />
      <text fg={theme.faint} content={detail} />
    </box>
  )
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <box style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
      <text fg={theme.cyan} content={`◌ ${label}…`} />
    </box>
  )
}

export function Modal({
  title,
  children,
  width = 64,
  height = 9,
}: {
  title: string
  children: ReactNode
  width?: number
  height?: number
}) {
  return (
    <box
      style={{
        position: "absolute",
        width: "100%",
        height: "100%",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#020711dd",
      }}
    >
      <box
        title={` ${title} `}
        style={{
          width,
          height,
          flexDirection: "column",
          border: true,
          borderStyle: "double",
          borderColor: theme.cyan,
          backgroundColor: theme.panelAlt,
          padding: 1,
        }}
      >
        {children}
      </box>
    </box>
  )
}

export function formatBytes(value?: number | null): string {
  if (value === undefined || value === null) return "—"
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MiB`
  return `${(value / 1024 ** 3).toFixed(1)} GiB`
}

export function formatAge(timestamp?: number | null): string {
  if (!timestamp) return "never"
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export function useVisibleRows<T>(items: T[], selected: number, height: number): { rows: T[]; start: number } {
  return useMemo(() => {
    const windowSize = Math.max(1, height)
    const start = Math.max(0, Math.min(selected - Math.floor(windowSize / 2), Math.max(0, items.length - windowSize)))
    return { rows: items.slice(start, start + windowSize), start }
  }, [items, selected, height])
}
