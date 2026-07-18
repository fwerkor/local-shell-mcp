import { describe, expect, test } from "bun:test"
import { appContentHeight, appContentWidth } from "./layout"

describe("app layout dimensions", () => {
  test("uses the drawable area inside the app padding", () => {
    expect(appContentWidth(47)).toBe(45)
    expect(appContentHeight(35)).toBe(27)
  })

  test("keeps a usable minimum for very small terminals", () => {
    expect(appContentWidth(1)).toBe(1)
    expect(appContentHeight(6)).toBe(1)
  })
})
