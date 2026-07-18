import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, Modal, Panel, useVisibleRows } from "./components"
import { handleSelectionScroll } from "./mouse"
import { clampIndex, nextValue, updateTodo } from "./state-utils"
import { screenTheme, theme } from "./theme"
import type { TodoItem, TodoPayload } from "./types"

const colors = screenTheme.Todos

type TodoDialog =
  | { type: "none" }
  | { type: "add" }
  | { type: "edit"; item: TodoItem }
  | { type: "delete"; item: TodoItem }

const STATUS_ORDER = ["pending", "in_progress", "completed"] as const
const PRIORITY_ORDER = ["low", "medium", "high"] as const

function statusIcon(status: string): string {
  if (status === "completed") return "✓"
  if (status === "in_progress") return "◐"
  return "○"
}

function statusColor(status: string): string {
  if (status === "completed") return theme.green
  if (status === "in_progress") return theme.yellow
  return theme.muted
}

function priorityColor(priority: string): string {
  if (priority === "high") return theme.red
  if (priority === "low") return theme.faint
  return theme.blue
}

export function TodosScreen({
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
  const [todos, setTodos] = useState<TodoItem[]>([])
  const [revision, setRevision] = useState(0)
  const [selected, setSelected] = useState(0)
  const [filter, setFilter] = useState<"all" | "open" | "completed">("all")
  const [dialog, setDialog] = useState<TodoDialog>({ type: "none" })
  const [saving, setSaving] = useState(false)
  const stateRef = useRef<{ todos: TodoItem[]; revision: number }>({ todos: [], revision: 0 })
  const mutationQueue = useRef<Promise<void>>(Promise.resolve())
  const pendingMutations = useRef(0)
  const mounted = useRef(true)

  const visible = useMemo(() => {
    if (filter === "open") return todos.filter((todo) => todo.status !== "completed")
    if (filter === "completed") return todos.filter((todo) => todo.status === "completed")
    return todos
  }, [filter, todos])
  const current = visible[clampIndex(selected, visible.length)]
  const listHeight = Math.max(5, height - 13)
  const { rows, start } = useVisibleRows(visible, selected, listHeight)

  const selectFilter = (next: "all" | "open" | "completed") => {
    setFilter(next)
    setSelected(0)
  }

  const cycleFilter = () => {
    setFilter((value) => (value === "all" ? "open" : value === "open" ? "completed" : "all"))
    setSelected(0)
  }

  const applyPayload = useCallback((payload: TodoPayload) => {
    const nextRevision = payload.revision || 0
    stateRef.current = { todos: payload.todos, revision: nextRevision }
    if (!mounted.current) return
    setTodos(payload.todos)
    setRevision(nextRevision)
    setSelected((value) => clampIndex(value, payload.todos.length))
  }, [])

  const load = useCallback(async () => {
    try {
      applyPayload(await api.todos())
    } catch (error) {
      if (mounted.current) setStatus(`Todos: ${formatError(error)}`)
    }
  }, [applyPayload, setStatus])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => {
      mounted.current = false
    }
  }, [load])

  useEffect(() => {
    onInteractionLockChange(dialog.type !== "none")
    return () => onInteractionLockChange(false)
  }, [dialog.type, onInteractionLockChange])

  const enqueueMutation = useCallback((
    mutate: (items: TodoItem[]) => TodoItem[],
    message?: string,
  ) => {
    pendingMutations.current += 1
    setSaving(true)
    const run = async () => {
      try {
        let base = stateRef.current
        let next = mutate(base.todos)
        let payload: TodoPayload
        try {
          payload = await api.writeTodos(next, base.revision)
        } catch (error) {
          const detail = formatError(error)
          if (!detail.includes("changed from revision")) throw error
          const latest = await api.todos()
          applyPayload(latest)
          base = stateRef.current
          next = mutate(base.todos)
          payload = await api.writeTodos(next, base.revision)
        }
        applyPayload(payload)
        if (message && mounted.current) setStatus(message)
      } catch (error) {
        if (mounted.current) setStatus(`Todos: ${formatError(error)}`)
      } finally {
        pendingMutations.current = Math.max(0, pendingMutations.current - 1)
        if (mounted.current) setSaving(pendingMutations.current > 0)
      }
    }
    mutationQueue.current = mutationQueue.current.then(run, run)
  }, [applyPayload, setStatus])

  const replaceItem = (id: string, update: Partial<TodoItem> | ((todo: TodoItem) => Partial<TodoItem>)) => {
    enqueueMutation((items) => updateTodo(items, id, update))
  }

  const addTodo = (content: string) => {
    const trimmed = content.trim()
    if (!trimmed) return
    const item: TodoItem = {
      id: `todo-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      content: trimmed,
      status: "pending",
      priority: "medium",
    }
    setDialog({ type: "none" })
    enqueueMutation((items) => [...items, item], "Todo added")
  }

  const editTodo = (content: string) => {
    if (dialog.type !== "edit") return
    const trimmed = content.trim()
    if (!trimmed) return
    const id = dialog.item.id
    setDialog({ type: "none" })
    replaceItem(id, { content: trimmed })
  }

  useKeyboard((key) => {
    if (!keyboardEnabled) return
    if (dialog.type === "add" || dialog.type === "edit") {
      if (key.name === "escape") setDialog({ type: "none" })
      return
    }
    if (dialog.type === "delete") {
      if (key.name === "escape" || key.name === "n") setDialog({ type: "none" })
      if (key.name === "y" || key.name === "return") {
        const id = dialog.item.id
        setDialog({ type: "none" })
        enqueueMutation((items) => items.filter((todo) => todo.id !== id), "Todo deleted")
      }
      return
    }
    if (key.name === "j" || key.name === "down") {
      setSelected((value) => clampIndex(value + 1, visible.length))
    } else if (key.name === "k" || key.name === "up") {
      setSelected((value) => clampIndex(value - 1, visible.length))
    } else if (key.name === "n") setDialog({ type: "add" })
    else if (key.name === "e" && current) setDialog({ type: "edit", item: current })
    else if (key.name === "d" && current) setDialog({ type: "delete", item: current })
    else if ((key.name === "return" || key.name === "space") && current) {
      replaceItem(current.id, (todo) => ({ status: nextValue(todo.status, STATUS_ORDER) }))
    } else if (key.name === "p" && current) {
      replaceItem(current.id, (todo) => ({ priority: nextValue(todo.priority, PRIORITY_ORDER) }))
    } else if (key.name === "f") {
      cycleFilter()
    } else if (key.name === "r" && pendingMutations.current === 0) void load()
  })

  const counts = {
    total: todos.length,
    open: todos.filter((todo) => todo.status !== "completed").length,
    completed: todos.filter((todo) => todo.status === "completed").length,
  }

  return (
    <box style={{ flexGrow: 1, flexDirection: "column" }}>
      {width < 76 ? (
        <Panel title="Summary" active accent={colors.accent} activeBackground={colors.panel} style={{ height: 3, alignItems: "center", justifyContent: "center" }}>
          <box style={{ flexDirection: "row" }}>
            <text onMouseDown={() => selectFilter("all")} fg={colors.accent} content={`A:${counts.total}  `} />
            <text onMouseDown={() => selectFilter("open")} fg={theme.yellow} content={`O:${counts.open}  `} />
            <text onMouseDown={() => selectFilter("completed")} fg={theme.green} content={`D:${counts.completed}  `} />
            <text onMouseDown={cycleFilter} fg={theme.muted} content={`V:${filter.slice(0, 1).toUpperCase()}`} />
          </box>
        </Panel>
      ) : (
        <box style={{ height: 4, flexDirection: "row", gap: 1 }}>
          {[
            { label: "All", value: counts.total, color: colors.accent, filter: "all" as const },
            { label: "Open", value: counts.open, color: theme.yellow, filter: "open" as const },
            { label: "Done", value: counts.completed, color: theme.green, filter: "completed" as const },
          ].map(({ label, value, color, filter: nextFilter }) => (
            <Panel key={label} title={label} onMouseDown={() => selectFilter(nextFilter)} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
              <text fg={color} attributes={1} content={String(value)} />
            </Panel>
          ))}
          <Panel title="View" active accent={colors.accent} activeBackground={colors.panel} onMouseDown={cycleFilter} style={{ width: Math.max(20, Math.floor(width * 0.2)), alignItems: "center", justifyContent: "center" }}>
            <text fg={colors.accent} attributes={1} content={filter.toUpperCase()} />
          </Panel>
        </box>
      )}
      <Panel title={`Todos · ${visible.length}`} active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, paddingTop: 1 }}>
        {visible.length === 0 ? (
          <EmptyState title="No matching todos" detail="Press n to add an item" />
        ) : (
          <box
            onMouseScroll={(event) => handleSelectionScroll(
              event,
              (delta) => setSelected((value) => clampIndex(value + delta, visible.length)),
            )}
            style={{ flexDirection: "column", flexGrow: 1 }}
          >
            {rows.map((todo, offset) => {
              const index = start + offset
              const active = index === selected
              return (
                <box
                  key={todo.id}
                  onMouseDown={() => setSelected(index)}
                  style={{
                    height: 3,
                    flexDirection: "row",
                    alignItems: "center",
                    paddingLeft: 1,
                    paddingRight: 1,
                    backgroundColor: active ? colors.selected : index % 2 ? theme.panelAlt : undefined,
                  }}
                >
                  <text fg={statusColor(todo.status)} attributes={1} content={`${statusIcon(todo.status)} `} />
                  <box style={{ flexDirection: "column", flexGrow: 1 }}>
                    <text
                      fg={todo.status === "completed" ? theme.faint : active ? theme.text : theme.muted}
                      attributes={active ? 1 : 0}
                      content={todo.content}
                    />
                    <text fg={theme.faint} content={todo.id} />
                  </box>
                  <box style={{ width: 10, alignItems: "center", justifyContent: "center", backgroundColor: theme.panelSoft }}>
                    <text fg={priorityColor(todo.priority)} attributes={1} content={todo.priority.toUpperCase()} />
                  </box>
                </box>
              )
            })}
          </box>
        )}
      </Panel>
      <KeyHint
        accent={colors.accent}
        items={[
          ["j/k", "move"],
          ["Enter", "status"],
          ["p", "priority"],
          ["n", "add"],
          ["e", "edit"],
          ["d", "delete"],
          ["f", "filter"],
          ["r", "refresh"],
        ]}
      />
      {saving && (
        <box style={{ position: "absolute", right: 2, top: 4, width: 14, height: 3, border: true, borderColor: theme.yellow, backgroundColor: theme.panelAlt, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.yellow} content="Saving…" />
        </box>
      )}
      {dialog.type === "add" && (
        <Modal title="Add todo" height={7}>
          <text fg={theme.muted} content="Describe the work item" />
          <box style={{ height: 3, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused placeholder="What needs to be done?" onSubmit={(value: unknown) => addTodo(typeof value === "string" ? value : "")} />
          </box>
          <text fg={theme.faint} content="Enter add · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "edit" && (
        <Modal title="Edit todo" height={7}>
          <text fg={theme.muted} content="Update the description" />
          <box style={{ height: 3, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused value={dialog.item.content} onSubmit={(value: unknown) => editTodo(typeof value === "string" ? value : "")} />
          </box>
          <text fg={theme.faint} content="Enter save · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "delete" && (
        <Modal title="Delete todo" height={7}>
          <text fg={theme.red} attributes={1} content="Delete this todo?" />
          <text fg={theme.muted} content={dialog.item.content} />
          <text fg={theme.faint} content="y / Enter confirm · n / Esc cancel" />
        </Modal>
      )}
    </box>
  )
}
