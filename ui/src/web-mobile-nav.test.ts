import { describe, expect, test } from "bun:test"

const markup = await Bun.file(new URL("../static/index.html", import.meta.url)).text()
const css = await Bun.file(new URL("./web.css", import.meta.url)).text()

describe("mobile WebUI navigation", () => {
  test("keeps all seven navigation destinations and accessible button names", () => {
    const nav = markup.match(/<nav class="primary-nav"[\s\S]*?<\/nav>/)?.[0]
    expect(nav).toBeDefined()
    const views = [...nav!.matchAll(/<button class="nav-item(?: active)?" type="button" data-view="([^"]+)" aria-label="([^"]+)">/g)]
    expect(views.map(([, view]) => view)).toEqual([
      "overview", "files", "terminals", "desktop", "sessions", "remotes", "audit",
    ])
    expect(views.every(([, , label]) => label.length > 0)).toBe(true)
  })

  test("keeps live workload and remote counts in accessible names", async () => {
    const script = await Bun.file(new URL("./web.ts", import.meta.url)).text()
    expect(script).toContain('machineNavCount.parentElement?.setAttribute("aria-label", `Remotes, ${remoteMachineCount} remote')
    expect(script).toContain('workloadNavCount.parentElement?.setAttribute("aria-label", `Terminals, ${activeWorkloadCount}')
    expect(script).toContain("remoteMachineCount === 1")
    expect(script).toContain("activeWorkloadCount === 1")
  })

  test("keeps 100vh fallbacks before 100dvh console sizing", () => {
    const mobile = css.split("@media (max-width: 720px) {")[1]?.split("@media (prefers-color-scheme")[0] || ""
    for (const selector of [".console-content", ".console-content .terminal-card"]) {
      const rule = mobile.split(`${selector} {`)[1]?.split("}")[0] || ""
      expect(rule).toMatch(/height: calc\(100vh[^;]*; height: calc\(100dvh/)
    }
  })

  test("lays out all destinations in one row on phones", () => {
    const mobile = css.split("@media (max-width: 720px) {")[1]?.split("@media (prefers-color-scheme")[0]
    expect(mobile).toBeDefined()
    expect(mobile).toContain("grid-template-columns: repeat(7, minmax(0, 1fr))")
    expect(mobile).toContain("env(safe-area-inset-bottom, 0px)")
    expect(mobile).toContain(".nav-item > span:nth-child(2) { display: block;")
  })
})
