export interface BrowserShortcutEvent {
  key: string
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
  "6": "\u001b[18~",
}

const browserShortcutSequences: Record<string, string> = {
  a: "\u001b[97;3u",
  n: "\u001b[110;3u",
  r: "\u001b[114;3u",
  w: "\u001b[119;3u",
  arrowleft: "\u001b[1;3D",
  arrowright: "\u001b[1;3C",
  "[": "\u001b[91;3u",
  "]": "\u001b[93;3u",
}

export function browserShortcutSequence(event: BrowserShortcutEvent): string | undefined {
  if (event.ctrlKey || event.metaKey || !event.altKey) return undefined
  return categorySequences[event.key] || browserShortcutSequences[event.key.toLowerCase()]
}
