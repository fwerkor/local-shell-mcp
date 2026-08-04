import { describe, expect, test } from "bun:test"

const stylesheets = ["web.css", "web-native.css"] as const

describe("WebUI typography", () => {
  for (const stylesheet of stylesheets) {
    test(`${stylesheet} does not use unreadable sub-9px text`, async () => {
      const source = await Bun.file(new URL(`./${stylesheet}`, import.meta.url)).text()
      const tinyDeclarations = Array.from(
        source.matchAll(/(?:font-size|font):\s*(\d+)px/g),
        (match) => ({ declaration: match[0], size: Number(match[1]) }),
      ).filter(({ size }) => size < 9)

      expect(tinyDeclarations).toEqual([])
    })
  }
})
