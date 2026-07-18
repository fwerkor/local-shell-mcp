import { describe, expect, test } from "bun:test"
import { selectionDeltaFromScroll } from "./mouse"

describe("selectionDeltaFromScroll", () => {
  test("moves list selection by three rows per wheel step", () => {
    expect(selectionDeltaFromScroll({ direction: "up", delta: 1 })).toBe(-3)
    expect(selectionDeltaFromScroll({ direction: "down", delta: 1 })).toBe(3)
  })

  test("allows compact lists to move one row at a time", () => {
    expect(selectionDeltaFromScroll({ direction: "up", delta: 1 }, 1)).toBe(-1)
    expect(selectionDeltaFromScroll({ direction: "down", delta: 1 }, 1)).toBe(1)
  })

  test("ignores horizontal scrolling", () => {
    expect(selectionDeltaFromScroll({ direction: "left", delta: 1 })).toBe(0)
    expect(selectionDeltaFromScroll({ direction: "right", delta: 1 })).toBe(0)
  })

  test("bounds accelerated trackpad deltas", () => {
    expect(selectionDeltaFromScroll({ direction: "down", delta: 20 })).toBe(12)
    expect(selectionDeltaFromScroll({ direction: "up", delta: 0 })).toBe(-3)
  })
})
