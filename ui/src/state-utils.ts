import type { TodoItem } from "./types"

export function clampIndex(value: number, length: number): number {
  if (length <= 0) return 0
  return Math.max(0, Math.min(value, length - 1))
}


export function scopedItems<T>(owner: string | null, current: string, items: T[]): T[] {
  return owner === current ? items : []
}

export function payloadMatches(
  payload: { machine: string; path?: string } | null,
  machine: string,
  path?: string,
): boolean {
  return Boolean(payload && payload.machine === machine && (path === undefined || payload.path === path))
}

export function nextValue<T extends string>(current: string, order: readonly T[]): T {
  const index = order.indexOf(current as T)
  return order[(index + 1 + order.length) % order.length]!
}

export function updateTodo(
  todos: TodoItem[],
  id: string,
  update: Partial<TodoItem> | ((todo: TodoItem) => Partial<TodoItem>),
): TodoItem[] {
  return todos.map((todo) => {
    if (todo.id !== id) return todo
    const patch = typeof update === "function" ? update(todo) : update
    return { ...todo, ...patch }
  })
}
