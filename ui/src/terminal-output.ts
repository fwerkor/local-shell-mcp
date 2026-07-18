const ANSI_ESCAPE = /\x1b\[[0-?]*[ -/]*[@-~]/g
const ANSI_ESCAPE_PREFIX = /^\x1b\[[0-?]*[ -/]*[@-~]/
const ANSI_RESET = "\x1b[0m"
const GRAPHEME_SEGMENTER = new Intl.Segmenter(undefined, { granularity: "grapheme" })
const UNICODE_MARK = /^\p{Mark}+$/u

function isWideCodePoint(codePoint: number): boolean {
  return codePoint >= 0x1100 && (
    codePoint <= 0x115f
    || codePoint === 0x2329
    || codePoint === 0x232a
    || (codePoint >= 0x2e80 && codePoint <= 0xa4cf && codePoint !== 0x303f)
    || (codePoint >= 0xac00 && codePoint <= 0xd7a3)
    || (codePoint >= 0xf900 && codePoint <= 0xfaff)
    || (codePoint >= 0xfe10 && codePoint <= 0xfe19)
    || (codePoint >= 0xfe30 && codePoint <= 0xfe6f)
    || (codePoint >= 0xff00 && codePoint <= 0xff60)
    || (codePoint >= 0xffe0 && codePoint <= 0xffe6)
    || (codePoint >= 0x1f1e6 && codePoint <= 0x1f1ff)
    || (codePoint >= 0x1f300 && codePoint <= 0x1faff)
    || (codePoint >= 0x20000 && codePoint <= 0x3fffd)
  )
}

export function terminalCellWidth(grapheme: string): number {
  let hasVisible = false
  for (const character of grapheme) {
    const codePoint = character.codePointAt(0)!
    if (
      codePoint === 0x200d
      || (codePoint >= 0xfe00 && codePoint <= 0xfe0f)
      || (codePoint >= 0xe0100 && codePoint <= 0xe01ef)
      || UNICODE_MARK.test(character)
    ) continue
    if (codePoint < 0x20 || (codePoint >= 0x7f && codePoint < 0xa0)) continue
    hasVisible = true
    if (isWideCodePoint(codePoint)) return 2
  }
  return hasVisible ? 1 : 0
}

function nextSgrState(current: string, escape: string): string {
  if (!escape.endsWith("m")) return current
  const rawParameters = escape.slice(2, -1)
  const parameters = rawParameters === "" ? [0] : rawParameters.split(";").map((value) => Number(value || 0))
  const lastReset = parameters.lastIndexOf(0)
  if (lastReset < 0) return current + escape
  const remaining = parameters.slice(lastReset + 1)
  return remaining.length > 0 ? `\x1b[${remaining.join(";")}m` : ""
}

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
  let activeSgr = ""
  let visibleColumns = 0
  let index = 0

  const emitRow = () => {
    rows.push(activeSgr ? `${current}${ANSI_RESET}` : current)
    current = activeSgr
    visibleColumns = 0
  }

  while (index < line.length) {
    const remainder = line.slice(index)
    const escape = remainder.match(ANSI_ESCAPE_PREFIX)?.[0]
    if (escape) {
      current += escape
      activeSgr = nextSgrState(activeSgr, escape)
      index += escape.length
      continue
    }

    const nextEscape = remainder.indexOf("\x1b")
    const plainText = nextEscape < 0 ? remainder : remainder.slice(0, nextEscape)
    const segment = GRAPHEME_SEGMENTER.segment(plainText)[Symbol.iterator]().next().value?.segment
    if (!segment) {
      current += remainder[0] || ""
      index += 1
      continue
    }
    const cellWidth = terminalCellWidth(segment)
    if (visibleColumns > 0 && visibleColumns + cellWidth > width) emitRow()
    current += segment
    visibleColumns += cellWidth
    index += segment.length
  }
  rows.push(activeSgr ? `${current}${ANSI_RESET}` : current)
  return rows
}

export function terminalDisplayRows(output: string, columns: number): string[] {
  return terminalOutputLines(output).flatMap((line) => wrapTerminalLine(line, columns))
}

export function terminalViewportRows(screenHeight: number): number {
  return Math.max(3, screenHeight - 15)
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
