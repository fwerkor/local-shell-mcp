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
    expect(markup).toContain('aria-controls="navigation"')
    expect(markup).toContain('aria-label="Close navigation"')
  })
  test("keeps live counts in accessible names", async () => {
    const source = await Bun.file(new URL("./web.ts",import.meta.url)).text()
    expect(source).toContain('machineNavCount.parentElement?.setAttribute("aria-label", `Remotes, ${remoteMachineCount} remote')
    expect(source).toContain('workloadNavCount.parentElement?.setAttribute("aria-label", `Terminals, ${activeWorkloadCount}')
  })
})
