export function appContentWidth(terminalWidth: number): number {
  return Math.max(1, terminalWidth - 2)
}

export function appContentHeight(terminalHeight: number): number {
  // App padding consumes two rows. Top navigation, its margin, and the
  // two-row status line consume another six rows.
  return Math.max(1, terminalHeight - 8)
}
