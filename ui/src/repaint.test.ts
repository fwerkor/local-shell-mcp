import { describe, expect, test } from "bun:test"
import { RGBA } from "@opentui/core"
import { forceFullRepaint } from "./repaint"
import { theme } from "./theme"

describe("forceFullRepaint", () => {
  test("invalidates the previous frame before requesting a render", () => {
    const calls: string[] = []
    const invalidations: RGBA[] = []
    const renderer = {
      currentRenderBuffer: {
        clear: (value: RGBA) => {
          invalidations.push(value)
          calls.push("clear")
        },
      },
      requestRender: () => calls.push("render"),
    }

    forceFullRepaint(renderer as never)

    expect(calls).toEqual(["clear", "render"])
    expect(invalidations[0]!.toInts()).not.toEqual(RGBA.fromHex(theme.bg).toInts())
  })
})
