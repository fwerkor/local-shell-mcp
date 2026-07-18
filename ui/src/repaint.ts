import { RGBA, type CliRenderer } from "@opentui/core"

type RepaintRenderer = Pick<CliRenderer, "currentRenderBuffer" | "requestRender">

const repaintSentinel = RGBA.fromInts(1, 2, 3, 4)

export function forceFullRepaint(renderer: RepaintRenderer): void {
  // OpenTUI normally sends only changed cells. Some mobile canvas renderers
  // retain pixels from a previous frame after resize or top-level navigation,
  // so invalidate the comparison buffer and repaint the full surface once.
  renderer.currentRenderBuffer.clear(repaintSentinel)
  renderer.requestRender()
}
