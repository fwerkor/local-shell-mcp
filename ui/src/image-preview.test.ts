import { describe, expect, test } from "bun:test"
import type { OptimizedBuffer, Renderable } from "@opentui/core"
import { drawClippedSuperSampleBuffer } from "./image-preview"

describe("image preview rendering", () => {
  test("clips supersampled pixels to the render box", () => {
    const calls: unknown[][] = []
    const pixels = new Uint8Array(8 * 6 * 4)
    const buffer = {
      pushScissorRect: (...args: unknown[]) => calls.push(["push", ...args]),
      drawSuperSampleBuffer: (...args: unknown[]) => calls.push(["draw", ...args]),
      popScissorRect: () => calls.push(["pop"]),
    } as unknown as OptimizedBuffer
    const renderable = {
      screenX: 12,
      screenY: 5,
      width: 4,
      height: 3,
    } as Pick<Renderable, "screenX" | "screenY" | "width" | "height">

    drawClippedSuperSampleBuffer(buffer, renderable, pixels, 8)

    expect(calls[0]).toEqual(["push", 12, 5, 4, 3])
    expect(calls[1]).toEqual(["draw", 12, 5, pixels, pixels.byteLength, "rgba8unorm", 32])
    expect(calls[2]).toEqual(["pop"])
  })

  test("restores the scissor stack when drawing fails", () => {
    let popped = false
    const buffer = {
      pushScissorRect: () => undefined,
      drawSuperSampleBuffer: () => {
        throw new Error("draw failed")
      },
      popScissorRect: () => {
        popped = true
      },
    } as unknown as OptimizedBuffer
    const renderable = {
      screenX: 0,
      screenY: 0,
      width: 1,
      height: 1,
    } as Pick<Renderable, "screenX" | "screenY" | "width" | "height">

    expect(() => drawClippedSuperSampleBuffer(buffer, renderable, new Uint8Array(16), 2)).toThrow("draw failed")
    expect(popped).toBe(true)
  })
})
