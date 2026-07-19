const NARROW_BREAKPOINT = 70
const COMPACT_BREAKPOINT = 105
const MACHINE_SIDEBAR_WIDTH = 23
const PANE_GAP = 1

export interface FilesLayout {
  narrow: boolean
  compact: boolean
  parentWidth: number
  currentWidth: number
  previewWidth: number
}

export function calculateFilesLayout(width: number): FilesLayout {
  const availableWidth = Math.max(1, Math.floor(width))
  const narrow = availableWidth < NARROW_BREAKPOINT
  const compact = availableWidth < COMPACT_BREAKPOINT

  if (narrow) {
    return {
      narrow,
      compact,
      parentWidth: 0,
      currentWidth: availableWidth,
      previewWidth: availableWidth,
    }
  }

  if (compact) {
    const paneWidth = Math.max(2, availableWidth - PANE_GAP)
    const currentWidth = Math.floor(paneWidth * 0.48)
    return {
      narrow,
      compact,
      parentWidth: 0,
      currentWidth,
      previewWidth: paneWidth - currentWidth,
    }
  }

  const mainWidth = Math.max(3, availableWidth - MACHINE_SIDEBAR_WIDTH - PANE_GAP)
  const paneWidth = Math.max(3, mainWidth - PANE_GAP * 2)
  const parentWidth = Math.floor(paneWidth * 0.24)
  const currentWidth = Math.floor(paneWidth * 0.38)
  return {
    narrow,
    compact,
    parentWidth,
    currentWidth,
    previewWidth: paneWidth - parentWidth - currentWidth,
  }
}
