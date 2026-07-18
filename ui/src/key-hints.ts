export interface KeyHintItem {
  key: string
  label: string
  onPress?: () => void
  disabled?: boolean
}

export interface KeyHintLayout {
  items: KeyHintItem[]
  clipped: boolean
  keysOnly: boolean
}

function fitKeyHints(items: KeyHintItem[], width: number, keysOnly: boolean, compact: boolean): KeyHintLayout {
  const budget = Math.max(8, width - 4)
  const visible: KeyHintItem[] = []
  let used = 0

  for (const item of items) {
    const label = keysOnly ? "" : compact ? item.label.slice(0, 7) : item.label
    const buttonPadding = item.onPress ? 2 : 0
    const gap = visible.length ? (keysOnly ? 1 : 2) : 0
    const segmentLength = item.key.length + (label ? label.length + 1 : 0) + buttonPadding + gap
    if (used + segmentLength > budget - 2) break
    visible.push({ ...item, label })
    used += segmentLength
  }

  return {
    items: visible,
    clipped: visible.length < items.length,
    keysOnly,
  }
}

export function layoutKeyHints(items: KeyHintItem[], width: number): KeyHintLayout {
  const preferredKeysOnly = width < 60
  const preferred = fitKeyHints(items, width, preferredKeysOnly, width < 92)
  if (!preferred.clipped || preferredKeysOnly) return preferred

  return fitKeyHints(items, width, true, false)
}
