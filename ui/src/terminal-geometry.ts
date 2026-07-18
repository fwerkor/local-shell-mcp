export const DEFAULT_TERMINAL_CELL_ASPECT = 2
const MIN_TERMINAL_CELL_ASPECT = 0.5
const MAX_TERMINAL_CELL_ASPECT = 5

function validCellAspect(value: number): number | null {
  if (!Number.isFinite(value)) return null
  if (value < MIN_TERMINAL_CELL_ASPECT || value > MAX_TERMINAL_CELL_ASPECT) return null
  return value
}

export function measureTerminalCellAspect(
  screenWidth: number,
  screenHeight: number,
  columns: number,
  rows: number,
): number | null {
  if (screenWidth <= 0 || screenHeight <= 0 || columns <= 0 || rows <= 0) return null
  const cellWidth = screenWidth / columns
  const cellHeight = screenHeight / rows
  return validCellAspect(cellHeight / cellWidth)
}

export function parseTerminalCellAspect(raw: string | undefined): number {
  return validCellAspect(Number(raw)) ?? DEFAULT_TERMINAL_CELL_ASPECT
}
