import type { MouseEvent as OpenTUIMouseEvent, ScrollInfo } from "@opentui/core"

export function selectionDeltaFromScroll(scroll: ScrollInfo | undefined, rowsPerStep = 3): number {
  if (!scroll || (scroll.direction !== "up" && scroll.direction !== "down")) return 0
  const steps = Math.max(1, Math.min(4, Math.ceil(Math.abs(scroll.delta || 1))))
  return (scroll.direction === "down" ? 1 : -1) * steps * Math.max(1, rowsPerStep)
}

export function handleSelectionScroll(
  event: OpenTUIMouseEvent,
  moveSelection: (delta: number) => void,
  rowsPerStep = 3,
): void {
  const delta = selectionDeltaFromScroll(event.scroll, rowsPerStep)
  if (!delta) return
  event.preventDefault()
  event.stopPropagation()
  moveSelection(delta)
}
