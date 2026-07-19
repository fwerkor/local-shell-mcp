import { describe, expect, test } from "bun:test"
import { todoVisibleRowCount } from "./todos-layout"

describe("todoVisibleRowCount", () => {
  test("accounts for three-row todo entries in a wide terminal", () => {
    expect(todoVisibleRowCount(172, 37)).toBe(9)
  })

  test("uses the shorter summary panel in narrow terminals", () => {
    expect(todoVisibleRowCount(60, 30)).toBe(7)
  })

  test("keeps at least one selectable row in very short terminals", () => {
    expect(todoVisibleRowCount(60, 5)).toBe(1)
  })
})
