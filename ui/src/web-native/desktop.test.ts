import { describe, expect, test } from "bun:test"
import { framePoint, wheelScrollAmount } from "./desktop"

describe("Native WebUI desktop coordinate mapping", () => {
  test("maps rendered image coordinates back to logical window pixels", () => {
    const rect = { left: 100, top: 50, right: 900, bottom: 500, width: 800, height: 450 }
    const bounds = { x: 1400, y: 200, width: 1600, height: 900 }

    expect(framePoint(100, 50, rect, bounds)).toEqual({ x: 0, y: 0 })
    expect(framePoint(500, 275, rect, bounds)).toEqual({ x: 800, y: 450 })
    expect(framePoint(899.9, 499.9, rect, bounds)).toEqual({ x: 1599, y: 899 })
  })

  test("rejects pointer positions outside the rendered frame", () => {
    const rect = { left: 10, top: 10, right: 110, bottom: 60, width: 100, height: 50 }
    const bounds = { x: 0, y: 0, width: 200, height: 100 }

    expect(framePoint(9, 20, rect, bounds)).toBeNull()
    expect(framePoint(110, 20, rect, bounds)).toBeNull()
    expect(framePoint(20, 60, rect, bounds)).toBeNull()
  })
})

describe("Native WebUI desktop wheel mapping", () => {
  test("keeps zero a no-op and maps browser-down to native-down", () => {
    expect(wheelScrollAmount(0)).toBe(0)
    expect(wheelScrollAmount(10)).toBe(-1)
    expect(wheelScrollAmount(-10)).toBe(1)
    expect(wheelScrollAmount(10000)).toBe(-12)
  })
})
