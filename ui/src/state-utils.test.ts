import { describe, expect, test } from "bun:test"
import { clampIndex, nextValue, updateTodo } from "./state-utils"

describe("clampIndex", () => {
  test("never produces a negative selection for an empty list", () => {
    expect(clampIndex(3, 0)).toBe(0)
    expect(clampIndex(-1, 0)).toBe(0)
  })

  test("keeps selection inside a non-empty list", () => {
    expect(clampIndex(-2, 3)).toBe(0)
    expect(clampIndex(8, 3)).toBe(2)
  })
})

describe("todo mutations", () => {
  const todos = [{ id: "a", content: "A", status: "pending", priority: "medium" }]

  test("cycles unknown and known values safely", () => {
    expect(nextValue("pending", ["pending", "in_progress", "completed"] as const)).toBe("in_progress")
    expect(nextValue("unknown", ["low", "medium", "high"] as const)).toBe("low")
  })

  test("applies updates to the latest matching item", () => {
    expect(updateTodo(todos, "a", (todo) => ({ content: `${todo.content}!` }))[0]!.content).toBe("A!")
    expect(updateTodo(todos, "missing", { content: "ignored" })).toEqual(todos)
  })
})
