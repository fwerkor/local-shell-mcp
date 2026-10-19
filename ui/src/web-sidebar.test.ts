import { describe, expect, test } from "bun:test"

describe("WebUI sidebar", () => {
  test("keeps the interface switch without duplicating Open TUI in navigation", async () => {
    const html = await Bun.file(new URL("../static/index.html", import.meta.url)).text()
    const sidebar = html.match(/<aside class="sidebar">([\s\S]*?)<\/aside>/)?.[1]

    expect(sidebar).toBeDefined()
    expect(sidebar).toContain('data-interface-mode="tui"')
    expect(sidebar).not.toContain('data-view="console"')
    expect(sidebar).not.toContain('class="sidebar-section-label"')
    expect(sidebar).toContain('id="controller-status"')
  })
})
