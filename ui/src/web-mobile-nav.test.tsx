/** @jsxImportSource react */
import { describe, expect, test } from "bun:test"
import { renderToStaticMarkup } from "react-dom/server"
import { ApplicationShell } from "./web-app"

describe("WebUI navigation", () => {
  test("keeps all seven destinations accessible in the shared navigation", () => {
    const markup = renderToStaticMarkup(<ApplicationShell />)
    const views = [...markup.matchAll(/data-view="([^"]+)" aria-label="([^"]+)"/g)]
    expect(views.map(([,view]) => view)).toEqual(["overview","files","terminals","desktop","sessions","remotes","audit"])
    expect(views.every(([, ,label]) => label.length > 0)).toBe(true)
    expect(markup).toContain('data-interface-mode="chat" aria-pressed="false" hidden')
    expect(markup).toContain('>Workspace</strong>')
    expect(markup.indexOf('data-interface-mode="chat"')).toBeGreaterThan(markup.indexOf('data-interface-mode="tui"'))
    expect(markup.indexOf('data-interface-mode="chat"')).toBeLessThan(markup.indexOf('class="navigation-label"'))
    expect(markup).toContain('aria-controls="navigation"')
    expect(markup).toContain('aria-label="Close navigation"')
  })
  test("keeps the remote count accessible without inventing a terminal count", async () => {
    const source = await Bun.file(new URL("./web.ts",import.meta.url)).text()
    expect(source).toContain('machineNavCount.parentElement?.setAttribute("aria-label", `Remotes, ${remoteMachineCount} remote')
    expect(source).not.toContain("workloadNavCount")
    const markup = renderToStaticMarkup(<ApplicationShell />)
    expect(markup).not.toContain('id="workload-nav-count"')
    expect(markup).toContain('aria-label="Terminals"')
  })
})
