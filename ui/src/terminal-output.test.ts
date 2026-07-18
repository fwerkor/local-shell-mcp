import { describe, expect, test } from "bun:test"
import {
  terminalCellWidth,
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

  test("wraps long rows and carries ANSI styles across render rows", () => {
    expect(wrapTerminalLine("abcdefgh", 3)).toEqual(["abc", "def", "gh"])
    expect(wrapTerminalLine("\x1b[31mabcdef\x1b[0m", 3)).toEqual([
      "\x1b[31mabc\x1b[0m",
      "\x1b[31mdef\x1b[0m",
    ])
    expect(wrapTerminalLine("\x1b[38;2;0;255;0mabcdef\x1b[0m", 3)).toEqual([
      "\x1b[38;2;0;255;0mabc\x1b[0m",
      "\x1b[38;2;0;255;0mdef\x1b[0m",
    ])
    expect(wrapTerminalLine("\x1b[38;5;0mabcdef\x1b[0m", 3)).toEqual([
      "\x1b[38;5;0mabc\x1b[0m",
      "\x1b[38;5;0mdef\x1b[0m",
    ])
    expect(terminalDisplayRows("abcdef\nxy", 3)).toEqual(["abc", "def", "xy"])
  })

  test("counts terminal cells for CJK, combining marks, and emoji", () => {
    expect(terminalCellWidth("a")).toBe(1)
    expect(terminalCellWidth("e\u0301")).toBe(1)
    expect(terminalCellWidth("界")).toBe(2)
    expect(terminalCellWidth("👩‍💻")).toBe(2)
    expect(wrapTerminalLine("中文ab", 4)).toEqual(["中文", "ab"])
  })

  test("keeps a useful viewport on common terminal heights", () => {
    expect(terminalViewportRows(19)).toBe(4)
    expect(terminalViewportRows(43)).toBe(28)
    expect(terminalViewportRows(10)).toBe(3)
  })
})
