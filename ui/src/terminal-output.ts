const ANSI_ESCAPE = /\x1b\[[0-?]*[ -/]*[@-~]/g
const ANSI_ESCAPE_PREFIX = /^\x1b\[[0-?]*[ -/]*[@-~]/

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

export function wrapTerminalLine(line: string, columns: number): string[] {
  const width = Math.max(1, columns)
  const rows: string[] = []
  let current = ""
  let visibleColumns = 0
  let index = 0
  while (index < line.length) {
    const remainder = line.slice(index)
    const escape = remainder.match(ANSI_ESCAPE_PREFIX)?.[0]
    if (escape) {
      current += escape
      index += escape.length
      continue
    }
    if (visibleColumns >= width) {
      rows.push(current)
      current = ""
      visibleColumns = 0
    }
    const codePoint = line.codePointAt(index)
    if (codePoint === undefined) break
    const character = String.fromCodePoint(codePoint)
    current += character
    visibleColumns += 1
    index += character.length
  }
  rows.push(current)
  return rows
}

export function terminalDisplayRows(output: string, columns: number): string[] {
  return terminalOutputLines(output).flatMap((line) => wrapTerminalLine(line, columns))
}

export function terminalViewportRows(screenHeight: number): number {
  return Math.max(3, screenHeight - 15)
}

export function appendedTerminalRows(previous: string[], next: string[]): number {
  const maxOverlap = Math.min(previous.length, next.length)
  for (let overlap = maxOverlap; overlap > 0; overlap -= 1) {
    let matches = true
    for (let index = 0; index < overlap; index += 1) {
      if (previous[previous.length - overlap + index] !== next[index]) {
        matches = false
        break
      }
    }
    if (matches) return next.length - overlap
  }
  return Math.max(0, next.length - previous.length)
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
