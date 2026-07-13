import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, Modal, Panel, useVisibleRows } from "./components"
import { theme } from "./theme"
import type { TodoItem } from "./types"

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

export function TodosScreen({ width, height, setStatus }: { width: number; height: number; setStatus: (message: string) => void }) {
  const [todos, setTodos] = useState<TodoItem[]>([])
  const [revision, setRevision] = useState(0)
  const [selected, setSelected] = useState(0)
  const [filter, setFilter] = useState<"all" | "open" | "completed">("all")
  const [dialog, setDialog] = useState<TodoDialog>({ type: "none" })
  const [saving, setSaving] = useState(false)

  const visible = useMemo(() => {
    if (filter === "open") return todos.filter((todo) => todo.status !== "completed")
    if (filter === "completed") return todos.filter((todo) => todo.status === "completed")
    return todos
  }, [filter, todos])
  const current = visible[selected]
  const listHeight = Math.max(5, height - 13)
  const { rows, start } = useVisibleRows(visible, selected, listHeight)

  const load = useCallback(async () => {
    try {
      const payload = await api.todos()
      setTodos(payload.todos)
      setRevision(payload.revision || 0)
      setSelected((value) => Math.min(value, Math.max(0, payload.todos.length - 1)))
    } catch (error) {
      setStatus(`Todos: ${formatError(error)}`)
    }
  }, [setStatus])

  useEffect(() => {
    void load()
  }, [load])

  const save = async (next: TodoItem[], message?: string) => {
    setSaving(true)
    try {
      const payload = await api.writeTodos(next, revision)
      setTodos(payload.todos)
      setRevision(payload.revision || revision + 1)
      if (message) setStatus(message)
    } catch (error) {
      const detail = formatError(error)
      if (detail.includes("changed from revision")) {
        await load()
        setStatus("Todos changed elsewhere; reloaded the latest list")
      } else {
        setStatus(`Todos: ${detail}`)
      }
    } finally {
      setSaving(false)
    }
  }

  const replaceItem = (id: string, update: Partial<TodoItem>) => {
    const next = todos.map((todo) => (todo.id === id ? { ...todo, ...update } : todo))
    void save(next)
  }

  const addTodo = (content: string) => {
    const trimmed = content.trim()
    if (!trimmed) return
    const item: TodoItem = {
      id: `todo-${Date.now().toString(36)}`,
      content: trimmed,
      status: "pending",
      priority: "medium",
    }
    setDialog({ type: "none" })
    void save([...todos, item], "Todo added")
  }

  const editTodo = (content: string) => {
    if (dialog.type !== "edit") return
    const trimmed = content.trim()
    if (!trimmed) return
    setDialog({ type: "none" })
    replaceItem(dialog.item.id, { content: trimmed })
  }

  useKeyboard((key) => {
    if (dialog.type === "add" || dialog.type === "edit") {
      if (key.name === "escape") setDialog({ type: "none" })
      return
    }
    if (dialog.type === "delete") {
      if (key.name === "escape" || key.name === "n") setDialog({ type: "none" })
      if (key.name === "y" || key.name === "return") {
        const next = todos.filter((todo) => todo.id !== dialog.item.id)
        setDialog({ type: "none" })
        void save(next, "Todo deleted")
      }
      return
    }
    if (key.name === "j" || key.name === "down") setSelected((value) => Math.min(visible.length - 1, value + 1))
    else if (key.name === "k" || key.name === "up") setSelected((value) => Math.max(0, value - 1))
    else if (key.name === "n") setDialog({ type: "add" })
    else if (key.name === "e" && current) setDialog({ type: "edit", item: current })
    else if (key.name === "d" && current) setDialog({ type: "delete", item: current })
    else if ((key.name === "return" || key.name === "space") && current) {
      const index = STATUS_ORDER.indexOf(current.status as (typeof STATUS_ORDER)[number])
      replaceItem(current.id, { status: STATUS_ORDER[(index + 1 + STATUS_ORDER.length) % STATUS_ORDER.length] })
    } else if (key.name === "p" && current) {
      const index = PRIORITY_ORDER.indexOf(current.priority as (typeof PRIORITY_ORDER)[number])
      replaceItem(current.id, { priority: PRIORITY_ORDER[(index + 1 + PRIORITY_ORDER.length) % PRIORITY_ORDER.length] })
    } else if (key.name === "f") {
      setFilter((value) => (value === "all" ? "open" : value === "open" ? "completed" : "all"))
      setSelected(0)
    } else if (key.name === "r") void load()
  })

  const counts = {
    total: todos.length,
    open: todos.filter((todo) => todo.status !== "completed").length,
    completed: todos.filter((todo) => todo.status === "completed").length,
  }

  return (
    <box style={{ flexGrow: 1, flexDirection: "column" }}>
      <box style={{ height: 4, flexDirection: "row", gap: 1 }}>
        {[
          ["All", counts.total, theme.cyan],
          ["Open", counts.open, theme.yellow],
          ["Done", counts.completed, theme.green],
        ].map(([label, value, color]) => (
          <Panel key={String(label)} title={String(label)} style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
            <text fg={String(color)} attributes={1} content={String(value)} />
          </Panel>
        ))}
        <Panel title="View" active style={{ width: Math.max(20, Math.floor(width * 0.2)), alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.cyan} attributes={1} content={filter.toUpperCase()} />
        </Panel>
      </box>
      <Panel title={`Todos · ${visible.length}`} active style={{ flexGrow: 1, paddingTop: 1 }}>
        {visible.length === 0 ? (
          <EmptyState title="No matching todos" detail="Press n to add an item" />
        ) : (
          <box style={{ flexDirection: "column", flexGrow: 1 }}>
            {rows.map((todo, offset) => {
              const index = start + offset
              const active = index === selected
              return (
                <box
                  key={todo.id}
                  style={{
                    height: 3,
                    flexDirection: "row",
                    alignItems: "center",
                    paddingLeft: 1,
                    paddingRight: 1,
                    backgroundColor: active ? theme.selectedStrong : index % 2 ? theme.panelAlt : undefined,
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
