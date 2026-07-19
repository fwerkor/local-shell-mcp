export const TODO_ROW_HEIGHT = 3

const WIDE_SUMMARY_HEIGHT = 4
const NARROW_SUMMARY_HEIGHT = 3
const FOOTER_HEIGHT = 2
const PANEL_CHROME_HEIGHT = 3

export function todoVisibleRowCount(width: number, height: number): number {
  const summaryHeight = width < 76 ? NARROW_SUMMARY_HEIGHT : WIDE_SUMMARY_HEIGHT
  const availableHeight = height - summaryHeight - FOOTER_HEIGHT - PANEL_CHROME_HEIGHT
  return Math.max(1, Math.floor(availableHeight / TODO_ROW_HEIGHT))
}
