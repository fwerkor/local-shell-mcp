import { describe, expect, test } from "bun:test"
import { calculateFilesLayout } from "./files-layout"

describe("Files layout", () => {
  test("uses one full-width pane on narrow terminals", () => {
    expect(calculateFilesLayout(69)).toEqual({
      narrow: true,
      compact: true,
      parentWidth: 0,
      currentWidth: 69,
      previewWidth: 69,
    })
  })

  test("keeps compact two-pane tracks within the available width", () => {
    const layout = calculateFilesLayout(90)
    expect(layout.narrow).toBe(false)
    expect(layout.compact).toBe(true)
    expect(layout.parentWidth).toBe(0)
    expect(layout.currentWidth + layout.previewWidth + 1).toBe(90)
  })

  test("keeps wide three-pane tracks within the main area", () => {
    const layout = calculateFilesLayout(198)
    expect(layout.narrow).toBe(false)
    expect(layout.compact).toBe(false)
    expect(layout.parentWidth + layout.currentWidth + layout.previewWidth + 2).toBe(174)
  })

  test("switches layouts only at the responsive breakpoints", () => {
    expect(calculateFilesLayout(69).narrow).toBe(true)
    expect(calculateFilesLayout(70).narrow).toBe(false)
    expect(calculateFilesLayout(104).compact).toBe(true)
    expect(calculateFilesLayout(105).compact).toBe(false)
  })
})
