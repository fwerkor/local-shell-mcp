export type DashboardLayout = "wide" | "desktop" | "compact" | "minimal"

export interface TrendSample {
  timestamp: number
  cpu: number
  memory: number
  disk: number
  network: number
  load: number
}

export function dashboardLayout(width: number, height: number): DashboardLayout {
  if (width >= 170 && height >= 38) return "wide"
  if (width >= 118 && height >= 30) return "desktop"
  if (width >= 78 && height >= 24) return "compact"
  return "minimal"
}

export function clampPercent(value?: number | null): number {
  if (typeof value !== "number" || Number.isNaN(value)) return 0
  return Math.max(0, Math.min(100, value))
}

export function sparkline(values: number[], width: number): string {
  const glyphs = "▁▂▃▄▅▆▇█"
  if (width <= 0) return ""
  if (values.length === 0) return "·".repeat(width)
  const sampled = resample(values, width)
  const min = Math.min(...sampled)
  const max = Math.max(...sampled)
  const span = max - min
  return sampled
    .map((value) => {
      const normalized = span > 0 ? (value - min) / span : clampPercent(value) / 100
      return glyphs[Math.max(0, Math.min(glyphs.length - 1, Math.round(normalized * (glyphs.length - 1))))]!
    })
    .join("")
}

export function areaChart(values: number[], width: number, height: number): string[] {
  const chartWidth = Math.max(4, width)
  const chartHeight = Math.max(2, height)
  const sampled = resample(values.length ? values : [0], chartWidth).map(clampPercent)
  const rows: string[] = []
  for (let row = chartHeight; row >= 1; row -= 1) {
    const threshold = (row / chartHeight) * 100
    const lower = ((row - 1) / chartHeight) * 100
    rows.push(
      sampled
        .map((value) => {
          if (value >= threshold) return "█"
          if (value > lower) return "▄"
          return " "
        })
        .join(""),
    )
  }
  return rows
}

export function resample(values: number[], width: number): number[] {
  if (width <= 0) return []
  if (values.length === 0) return Array.from({ length: width }, () => 0)
  if (values.length === 1) return Array.from({ length: width }, () => values[0]!)
  return Array.from({ length: width }, (_, index) => {
    const position = (index * (values.length - 1)) / Math.max(1, width - 1)
    const left = Math.floor(position)
    const right = Math.min(values.length - 1, Math.ceil(position))
    const fraction = position - left
    return values[left]! * (1 - fraction) + values[right]! * fraction
  })
}

export function trendRangeLabel(timestamps: number[]): string {
  if (timestamps.length < 2) return "live"
  const span = Math.max(0, timestamps[timestamps.length - 1]! - timestamps[0]!)
  if (span < 1) return "live"
  if (span < 60) return `-${Math.round(span)}s`
  return `-${Math.max(1, Math.round(span / 60))}m`
}

export function formatDuration(seconds?: number | null): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "—"
  const whole = Math.floor(seconds)
  const days = Math.floor(whole / 86_400)
  const hours = Math.floor((whole % 86_400) / 3_600)
  const minutes = Math.floor((whole % 3_600) / 60)
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${whole % 60}s`
  return `${whole}s`
}

export function formatRate(bytesPerSecond?: number | null): string {
  if (typeof bytesPerSecond !== "number" || !Number.isFinite(bytesPerSecond)) return "—"
  if (bytesPerSecond < 1024) return `${Math.round(bytesPerSecond)} B/s`
  if (bytesPerSecond < 1024 ** 2) return `${(bytesPerSecond / 1024).toFixed(1)} KiB/s`
  if (bytesPerSecond < 1024 ** 3) return `${(bytesPerSecond / 1024 ** 2).toFixed(1)} MiB/s`
  return `${(bytesPerSecond / 1024 ** 3).toFixed(1)} GiB/s`
}

export function truncate(value: string, width: number): string {
  if (width <= 0) return ""
  if (value.length <= width) return value
  if (width === 1) return "…"
  return `${value.slice(0, width - 1)}…`
}
