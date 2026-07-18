import { describe, expect, test } from "bun:test"
import { ImageAddon } from "@xterm/addon-image"
import { WEB_IMAGE_ADDON_OPTIONS, createImageAddon } from "./image-support"

describe("WebUI inline images", () => {
  test("enables the image protocols used by OpenTUI and xterm.js", () => {
    expect(WEB_IMAGE_ADDON_OPTIONS.sixelSupport).toBe(true)
    expect(WEB_IMAGE_ADDON_OPTIONS.iipSupport).toBe(true)
    expect(WEB_IMAGE_ADDON_OPTIONS.enableSizeReports).toBe(true)
  })

  test("constructs the official xterm image addon", () => {
    expect(createImageAddon()).toBeInstanceOf(ImageAddon)
  })
})
