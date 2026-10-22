import { describe, expect, test } from "bun:test"

const readSource = (path: string) => Bun.file(new URL(path, import.meta.url)).text()

describe("WebUI information density", () => {
  test("shows one page heading without repeated introductions", async () => {
    const [html, web] = await Promise.all([readSource("../static/index.html"), readSource("./web.ts")])
    expect(html).toContain('id="page-title"')
    expect(html).not.toContain('id="page-description"')
    expect(html).not.toContain('id="page-name"')
    expect(html).not.toContain('class="breadcrumb"')
    expect(web).toContain("PAGE_TITLES[activeView]")
    expect(web).not.toContain("PAGE_COPY")
  })

  test("keeps the illustrated health banner, counters and actionable alert detail", async () => {
    const [web, css] = await Promise.all([readSource("./web.ts"), readSource("./web.css")])
    expect(web).toContain('class="status-illustration"')
    expect(web).toContain('class="status-stats"')
    expect(web).toContain('alerts[0]?.detail')
    expect(web).toContain('presentation.detail ? `<p>')
    expect(web).not.toContain("All systems operational")
    expect(css).toContain(".status-banner.attention")
    expect(css).toContain(".status-banner.critical")
    expect(css).toContain(".pulse-ring.outer")
  })
})
