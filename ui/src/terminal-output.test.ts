import { describe, expect, test } from "bun:test"
import {
  terminalOutputLines,
  terminalScrollLimit,
  visibleTerminalOutput,
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
})
