export interface BrowserShortcutEvent {
  key: string
  code?: string
  altKey: boolean
  ctrlKey: boolean
  metaKey: boolean
}

const categorySequences: Record<string, string> = {
  "1": "\u001bOQ",
  "2": "\u001bOR",
  "3": "\u001bOS",
  "4": "\u001b[15~",
  "5": "\u001b[17~",
}

export const BROWSER_QUIT_SEQUENCE = "\u001b[113;3u"

const browserShortcutSequences: Record<string, string> = {
  a: "\u001b[97;3u",
  n: "\u001b[110;3u",
  q: BROWSER_QUIT_SEQUENCE,
  r: "\u001b[114;3u",
  w: "\u001b[119;3u",
  arrowleft: "\u001b[1;3D",
  arrowright: "\u001b[1;3C",
  "[": "\u001b[91;3u",
  "]": "\u001b[93;3u",
}

function physicalShortcutKey(code: string | undefined): string | undefined {
  if (!code) return undefined
  if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase()
  if (/^Digit[0-9]$/.test(code)) return code.slice(5)
  if (code === "BracketLeft") return "["
  if (code === "BracketRight") return "]"
  if (code === "ArrowLeft") return "arrowleft"
  if (code === "ArrowRight") return "arrowright"
  return undefined
}

export function browserShortcutSequence(event: BrowserShortcutEvent): string | undefined {
  if (event.ctrlKey || event.metaKey || !event.altKey) return undefined
  const key = physicalShortcutKey(event.code) || event.key.toLowerCase()
  return categorySequences[key] || browserShortcutSequences[key]
}
