import type { OptimizedBuffer, Renderable } from "@opentui/core"
import { EmptyState, formatBytes } from "./components"
import { drawClippedSuperSampleBuffer } from "./image-preview"
import { theme } from "./theme"
import type { FilePreview } from "./types"

export function ImagePreviewView({
  preview,
  title,
  fallbackBytes = 0,
}: {
  preview: FilePreview
  title: string
  fallbackBytes?: number
}) {
  const pixelWidth = Number(preview.width || 0)
  const pixelHeight = Number(preview.height || 0)
  const cellWidth = Number(preview.cell_width || pixelWidth * 2)
  const cellHeight = Number(preview.cell_height || Math.ceil(pixelHeight / 2))
  let pixels: Uint8Array
  try {
    pixels = Uint8Array.from(Buffer.from(String(preview.rgba || ""), "base64"))
  } catch {
    return <EmptyState title={title} detail="Invalid image preview data" />
  }
  if (!pixelWidth || !pixelHeight || pixels.byteLength !== pixelWidth * pixelHeight * 4) {
    return <EmptyState title={title} detail="Invalid image preview dimensions" />
  }

  const sourceWidth = Number(preview.original_width || pixelWidth)
  const sourceHeight = Number(preview.original_height || pixelHeight)
  const drawPixels = function (this: Renderable, buffer: OptimizedBuffer) {
    drawClippedSuperSampleBuffer(buffer, this, pixels, pixelWidth)
  }

  return (
    <box
      style={{
        flexGrow: 1,
        minWidth: 0,
        minHeight: 0,
        overflow: "hidden",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <box
        style={{ width: cellWidth, height: cellHeight, flexShrink: 0 }}
        renderAfter={drawPixels}
      />
      <text
        fg={theme.faint}
        content={`${sourceWidth}×${sourceHeight} · ${formatBytes(Number(preview.bytes || fallbackBytes))}`}
      />
    </box>
  )
}
