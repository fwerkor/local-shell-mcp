import type { ScrollBoxRenderable } from "@opentui/core"

export interface PaneNavigationKey {
  name: string
  shift?: boolean
}

export function cyclePane<T>(panes: readonly T[], current: T, delta = 1): T {
  if (panes.length === 0) return current
  const currentIndex = Math.max(0, panes.indexOf(current))
  const nextIndex = (currentIndex + delta + panes.length) % panes.length
  return panes[nextIndex]!
}

export function scrollPaneForKey(
  pane: ScrollBoxRenderable | null | undefined,
  key: PaneNavigationKey,
): boolean {
  if (!pane) return false
  if (key.name === "j" || key.name === "down") {
    pane.scrollBy(1)
    return true
  }
  if (key.name === "k" || key.name === "up") {
    pane.scrollBy(-1)
    return true
  }
  if (key.name === "pagedown") {
    pane.scrollBy(0.8, "viewport")
    return true
  }
  if (key.name === "pageup") {
    pane.scrollBy(-0.8, "viewport")
    return true
  }
  if (key.name === "home") {
    pane.scrollTo(0)
    return true
  }
  if (key.name === "end") {
    pane.scrollTo(pane.scrollHeight)
    return true
  }
  return false
}
