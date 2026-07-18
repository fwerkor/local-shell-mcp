import { describe, expect, test } from "bun:test"
import { areaChart, dashboardLayout, formatDuration, formatRate, resample, sparkline, trendRangeLabel, truncate } from "./dashboard-utils"

describe("dashboard responsive layout", () => {
  test("uses the rich wide layout only when both dimensions allow it", () => {
    expect(dashboardLayout(198, 52)).toBe("wide")
    expect(dashboardLayout(198, 30)).toBe("desktop")
    expect(dashboardLayout(140, 40)).toBe("desktop")
    expect(dashboardLayout(96, 28)).toBe("compact")
    expect(dashboardLayout(70, 20)).toBe("minimal")
  })
})

describe("dashboard trends", () => {
  test("resamples data to the exact viewport width", () => {
    expect(resample([0, 100], 5)).toEqual([0, 25, 50, 75, 100])
    expect(resample([42], 3)).toEqual([42, 42, 42])
  })

  test("renders bounded sparklines and filled area charts", () => {
    expect(sparkline([0, 25, 50, 75, 100], 5)).toHaveLength(5)
    const chart = areaChart([0, 50, 100], 9, 4)
    expect(chart).toHaveLength(4)
    expect(chart.every((row) => row.length === 9)).toBe(true)
    expect(chart.join("")) .toContain("█")
  })
})

describe("dashboard formatting", () => {
  test("formats time and transfer rates compactly", () => {
    expect(formatDuration(65)).toBe("1m 5s")
    expect(formatDuration(90_000)).toBe("1d 1h")
    expect(formatRate(1536)).toBe("1.5 KiB/s")
    expect(trendRangeLabel([10])).toBe("live")
    expect(trendRangeLabel([10, 43])).toBe("-33s")
    expect(trendRangeLabel([10, 190])).toBe("-3m")
  })

  test("truncates without exceeding the available width", () => {
    expect(truncate("dashboard", 6)).toBe("dashb…")
    expect(truncate("ok", 6)).toBe("ok")
  })
})
