const ANSI_ESCAPE = /\x1b\[[0-?]*[ -/]*[@-~]/g

function isVisuallyBlank(line: string): boolean {
  return line.replace(ANSI_ESCAPE, "").trim().length === 0
}

export function terminalOutputLines(output: string): string[] {
  const lines = (output || "Terminal is ready.").split(/\r?\n/)
  while (lines.length > 1 && isVisuallyBlank(lines[lines.length - 1]!)) {
    lines.pop()
  }
  return lines
}

export function terminalScrollLimit(lineCount: number, rows: number): number {
  return Math.max(0, lineCount - Math.max(1, rows))
}

export function visibleTerminalLines(
  lines: string[],
  rows: number,
  scrollOffset: number,
): string[] {
  const viewportRows = Math.max(1, rows)
  const safeOffset = Math.max(0, Math.min(scrollOffset, terminalScrollLimit(lines.length, viewportRows)))
  const end = lines.length - safeOffset
  return lines.slice(Math.max(0, end - viewportRows), end)
}

export function visibleTerminalOutput(
  lines: string[],
  rows: number,
  scrollOffset: number,
): string {
  return visibleTerminalLines(lines, rows, scrollOffset).join("\n")
}
