import type { ReactNode } from "react"
import { useMemo } from "react"
import { useTerminalDimensions } from "@opentui/react"
import { layoutKeyHints } from "./key-hints"
import type { KeyHintItem } from "./key-hints"
import { handleSelectionScroll } from "./mouse"
import { clampIndex } from "./state-utils"
import type { Machine, ScreenName } from "./types"
import { screenTheme, theme } from "./theme"

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
  const narrow = width < 45
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
        borderColor: theme.border,
        backgroundColor: theme.panel,
      }}
    >
      <text fg={theme.text} attributes={1} content={compact ? "LSM" : "LOCAL SHELL"} />
      {!compact && <text fg={theme.cyan} attributes={1} content=" MCP" />}
      <text fg={theme.faint} content={narrow ? " " : "  /  "} />
      {SCREENS.map((screen) => {
        const selected = screen === active
        const colors = screenTheme[screen]
        const narrowInitial = screen === "Todos" ? "D" : screen[0]
        const label = narrow ? narrowInitial : compact ? screen.slice(0, 3) : screen
        return (
          <box
            key={screen}
            onMouseDown={() => onSelect(screen)}
            style={{
              height: 1,
              marginRight: narrow ? 0 : compact ? 1 : 2,
              paddingLeft: narrow ? 0 : 1,
              paddingRight: 1,
              backgroundColor: selected ? colors.selected : theme.panel,
            }}
          >
            <text fg={selected ? colors.accent : theme.muted} attributes={selected ? 1 : 0} content={label} />
          </box>
        )
      })}
      <box style={{ flexGrow: 1 }} />
    </box>
  )
}

export function MachineSidebar({
  machines,
  selected,
  title = "Machines",
  width = 23,
  accent = theme.cyan,
  selectedColor = theme.selected,
  onSelect,
}: {
  machines: Machine[]
  selected: string
  title?: string
  width?: number
  accent?: string
  selectedColor?: string
  onSelect?: (machine: string) => void
}) {
  const selectedIndex = machines.findIndex((machine) => machine.name === selected)
  return (
    <box
      title={` ${title} `}
      onMouseScroll={(event) => {
        if (!onSelect || machines.length === 0) return
        handleSelectionScroll(
          event,
          (delta) => onSelect(
            machines[clampIndex(Math.max(0, selectedIndex) + delta, machines.length)]!.name,
          ),
          1,
        )
      }}
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
            onMouseDown={() => onSelect?.(machine.name)}
            style={{
              height: 2,
              paddingLeft: 1,
              paddingRight: 1,
              flexDirection: "row",
              backgroundColor: active ? selectedColor : undefined,
            }}
          >
            <text fg={online ? theme.green : theme.faint} content={online ? "● " : "○ "} />
            <text fg={active ? accent : theme.muted} attributes={active ? 1 : 0} content={machine.name} />
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
  accent = theme.cyan,
  activeBackground = theme.panelAlt,
  children,
  style,
  onMouseDown,
}: {
  title: string
  active?: boolean
  accent?: string
  activeBackground?: string
  children?: ReactNode
  style?: Record<string, unknown>
  onMouseDown?: () => void
}) {
  return (
    <box
      title={` ${title} `}
      onMouseDown={onMouseDown}
      style={{
        flexDirection: "column",
        border: true,
        borderStyle: "rounded",
        borderColor: active ? accent : theme.border,
        backgroundColor: active ? activeBackground : theme.panel,
        ...style,
      }}
    >
      {children}
    </box>
  )
}

export function KeyHint({ items, accent = theme.cyan }: { items: KeyHintItem[]; accent?: string }) {
  const { width } = useTerminalDimensions()
  const { items: visible, clipped, keysOnly } = layoutKeyHints(items, width)
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
      {visible.map(({ key, label, onPress, disabled }) => {
        const clickable = Boolean(onPress) && !disabled
        return (
          <box
            key={`${key}-${label}`}
            onMouseDown={clickable ? onPress : undefined}
            style={{
              flexDirection: "row",
              marginRight: keysOnly ? 1 : 2,
              paddingLeft: onPress ? 1 : 0,
              paddingRight: onPress ? 1 : 0,
              backgroundColor: clickable ? theme.panelSoft : undefined,
            }}
          >
            <text fg={disabled ? theme.faint : accent} attributes={disabled ? 0 : 1} content={key} />
            {label && <text fg={disabled ? theme.faint : theme.muted} content={` ${label}`} />}
          </box>
        )
      })}
      {clipped && <text fg={theme.faint} content="…" />}
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
  const terminal = useTerminalDimensions()
  const actualWidth = Math.min(width, Math.max(16, terminal.width - 4))
  const actualHeight = Math.min(height, Math.max(6, terminal.height - 4))
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
          width: actualWidth,
          height: actualHeight,
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
    const safeSelected = clampIndex(selected, items.length)
    const start = Math.max(
      0,
      Math.min(safeSelected - Math.floor(windowSize / 2), Math.max(0, items.length - windowSize)),
    )
    return { rows: items.slice(start, start + windowSize), start }
  }, [items, selected, height])
}
