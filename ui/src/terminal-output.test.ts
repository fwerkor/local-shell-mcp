import { describe, expect, test } from "bun:test"
import {
  appendedTerminalRows,
  terminalDisplayRows,
  terminalOutputLines,
  terminalScrollLimit,
  terminalViewportRows,
  visibleTerminalOutput,
  wrapTerminalLine,
} from "./terminal-output"

describe("terminal output viewport", () => {
  test("removes blank pane rows after the meaningful terminal output", () => {
    expect(terminalOutputLines("prompt\nresult\n\n   \n")).toEqual(["prompt", "result"])
    expect(terminalOutputLines("prompt\n\x1b[0m   \n")).toEqual(["prompt"])
  })

  test("shows the newest rows without overestimating the viewport", () => {
    const lines = Array.from({ length: 8 }, (_, index) => `line-${index + 1}`)
    expect(visibleTerminalOutput(lines, 3, 0)).toBe("line-6\nline-7\nline-8")
    expect(terminalScrollLimit(lines.length, 3)).toBe(5)
  })

  test("moves backward through history and clamps excessive offsets", () => {
    const lines = Array.from({ length: 8 }, (_, index) => `line-${index + 1}`)
    expect(visibleTerminalOutput(lines, 3, 3)).toBe("line-3\nline-4\nline-5")
    expect(visibleTerminalOutput(lines, 3, 99)).toBe("line-1\nline-2\nline-3")
  })

  test("wraps long rows without counting ANSI control sequences", () => {
    expect(wrapTerminalLine("abcdefgh", 3)).toEqual(["abc", "def", "gh"])
    expect(wrapTerminalLine("\x1b[31mabcdef\x1b[0m", 3)).toEqual([
      "\x1b[31mabc",
      "def\x1b[0m",
    ])
    expect(terminalDisplayRows("abcdef\nxy", 3)).toEqual(["abc", "def", "xy"])
  })

  test("detects appended rows when a capped tail shifts", () => {
    expect(appendedTerminalRows(["1", "2", "3"], ["1", "2", "3", "4"])).toBe(1)
    expect(appendedTerminalRows(["1", "2", "3"], ["2", "3", "4"])).toBe(1)
    expect(appendedTerminalRows(["1", "2", "3"], ["changed", "rows", "only"])).toBe(0)
  })

  test("keeps a useful viewport on common terminal heights", () => {
    expect(terminalViewportRows(19)).toBe(4)
    expect(terminalViewportRows(43)).toBe(28)
    expect(terminalViewportRows(10)).toBe(3)
  })
})
