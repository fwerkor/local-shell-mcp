import { describe, expect, test } from "bun:test"
import {
  DEFAULT_TERMINAL_CELL_ASPECT,
  measureTerminalCellAspect,
  parseTerminalCellAspect,
} from "./terminal-geometry"

describe("terminal cell geometry", () => {
  test("measures the xterm cell height-to-width ratio", () => {
    expect(measureTerminalCellAspect(1508, 666, 232, 37)).toBeCloseTo(2.77, 2)
  })

  test("rejects missing or implausible measurements", () => {
    expect(measureTerminalCellAspect(0, 666, 232, 37)).toBeNull()
    expect(measureTerminalCellAspect(1508, 666, 0, 37)).toBeNull()
    expect(measureTerminalCellAspect(1000, 10, 100, 100)).toBeNull()
  })

  test("uses the native-terminal fallback for invalid environment values", () => {
    expect(parseTerminalCellAspect("2.75")).toBe(2.75)
    expect(parseTerminalCellAspect("not-a-number")).toBe(DEFAULT_TERMINAL_CELL_ASPECT)
    expect(parseTerminalCellAspect(undefined)).toBe(DEFAULT_TERMINAL_CELL_ASPECT)
  })
})
