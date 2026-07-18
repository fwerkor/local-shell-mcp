import type { OptimizedBuffer, Renderable } from "@opentui/core"

export function drawClippedSuperSampleBuffer(
  buffer: OptimizedBuffer,
  renderable: Pick<Renderable, "screenX" | "screenY" | "width" | "height">,
  pixels: Uint8Array,
  pixelWidth: number,
): void {
  if (renderable.width <= 0 || renderable.height <= 0) return

  buffer.pushScissorRect(
    renderable.screenX,
    renderable.screenY,
    renderable.width,
    renderable.height,
  )
  try {
    buffer.drawSuperSampleBuffer(
      renderable.screenX,
      renderable.screenY,
      pixels as never,
      pixels.byteLength,
      "rgba8unorm",
      pixelWidth * 4,
    )
  } finally {
    buffer.popScissorRect()
  }
}
