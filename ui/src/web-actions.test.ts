import { describe, expect, test } from "bun:test"

const nativePages = ["files", "terminals", "sessions", "remotes", "audit"] as const

describe("Native WebUI actions", () => {
  test("uses visible controls instead of shortcut footers", async () => {
    const sources = await Promise.all(
      nativePages.map((page) => Bun.file(new URL(`./web-native/${page}.ts`, import.meta.url)).text()),
    )

    expect(sources.join("\n")).not.toContain("shortcut-strip")
  })

  test("does not register document-wide single-key actions on ordinary WebUI pages", async () => {
    const sources = await Promise.all(
      ["files", "sessions", "remotes", "audit"].map((page) => Bun.file(new URL(`./web-native/${page}.ts`, import.meta.url)).text()),
    )

    for (const source of sources) expect(source).not.toContain('this.listen(document, "keydown"')
  })

  test("keeps file, session, and remote rows keyboard accessible within their page", async () => {
    const files = await Bun.file(new URL("./web-native/files.ts", import.meta.url)).text()
    const sessions = await Bun.file(new URL("./web-native/sessions.ts", import.meta.url)).text()
    const remotes = await Bun.file(new URL("./web-native/remotes.ts", import.meta.url)).text()

    for (const source of [sessions, remotes]) {
      expect(source).toContain('this.listen(root, "keydown"')
      expect(source).toContain('event.key === "ArrowDown"')
      expect(source).toContain('event.key === "Enter"')
    }
    for (const source of [sessions]) {
      expect(source).toContain("tabIndex = -1")
      expect(source).toContain("tabIndex = 0")
    }
    expect(remotes).toContain('tabindex="${selected ? "0" : "-1"}"')
    expect(sessions).toContain("data-session-id")
    expect(remotes).toContain("data-remote-name")
    expect(remotes).toContain("focusedName")
    expect(files).toContain("onSetPath:")
    expect(files).toContain("onRequestData:")
    expect(files).toContain("onDownloadFile:")
    expect(files).toContain('event.key === "Enter"')
  })

  test("rerenders remote details when reset queue state changes", async () => {
    const remotes = await Bun.file(new URL("./web-native/remotes.ts", import.meta.url)).text()
    const revision = remotes.slice(
      remotes.indexOf("function remoteDetailRevision"),
      remotes.indexOf("export class RemotesController"),
    )

    expect(revision).toContain("machine.queue_depth")
    expect(revision).toContain("machine.reset_generation")
  })

  test("locks Native WebUI reset while its request is in flight", async () => {
    const remotes = await Bun.file(new URL("./web-native/remotes.ts", import.meta.url)).text()
    const resetMethod = remotes.slice(
      remotes.indexOf("private async reset()"),
      remotes.indexOf("private async revoke()"),
    )

    expect(remotes).toContain("private resetRequestInFlight = false")
    expect(remotes).toContain("reset.disabled = !current || !this.enabled || this.resetRequestInFlight")
    expect(resetMethod).toContain("if (this.resetRequestInFlight) return")
    expect(resetMethod.match(/if \(this\.resetRequestInFlight\) return/g)?.length).toBe(2)
    expect(resetMethod).toContain("this.resetRequestInFlight = true")
    expect(resetMethod).toContain("this.resetRequestInFlight = false")
  })

  test("keeps the terminal overlay inside the terminal grid row", async () => {
    const styles = await Bun.file(new URL("./web-native.css", import.meta.url)).text()
    const overlayRule = styles.match(/\.terminal-overlay\s*\{([^}]*)\}/)?.[1] || ""

    expect(overlayRule).toContain("grid-row: 2")
    expect(overlayRule).not.toContain("inset:")
    expect(overlayRule).not.toContain("position: absolute")
  })

  test("exposes the previously shortcut-oriented operations as buttons", async () => {
    const files = await Bun.file(new URL("./web-native/files.ts", import.meta.url)).text()
    const audit = await Bun.file(new URL("./web-native/audit.ts", import.meta.url)).text()
    const terminals = await Bun.file(new URL("./web-native/terminals.ts", import.meta.url)).text()

    expect(files).toContain("onOpenFile:")
    expect(files).toContain("onDownloadFile:")
    expect(files).toContain('data-action="up"')
    expect(audit).toContain('data-action="previous-record"')
    expect(audit).toContain('data-action="next-record"')
    expect(audit).toContain('button("Advanced", "toggle-advanced")')
    expect(audit).not.toContain('button("Search", "search")')
    expect(terminals).toContain('"previous-session"')
    expect(terminals).toContain('"next-session"')
    for (const label of ["Copy", "Paste", "Find", "Clear", "Fullscreen"]) {
      expect(terminals).toContain(`button("${label}"`)
    }
  })

  test("uses one visibility-aware scheduler for native WebUI refreshes", async () => {
    const nativeSources = await Promise.all(
      nativePages.map((page) => Bun.file(new URL(`./web-native/${page}.ts`, import.meta.url)).text()),
    )
    const web = await Bun.file(new URL("./web.ts", import.meta.url)).text()

    for (const source of nativeSources) expect(source).not.toContain("this.every(")
    expect(web).toContain('document.visibilityState !== "hidden"')
    expect(web).toContain('document.addEventListener("visibilitychange"')
  })

  test("uses the shared WebUI refresh control instead of duplicating it inside native pages", async () => {
    const sources = await Promise.all(
      nativePages.map((page) => Bun.file(new URL(`./web-native/${page}.ts`, import.meta.url)).text()),
    )

    for (const source of sources) expect(source).not.toContain('button("Refresh"')
    expect(sources.join("\n")).not.toContain("refresh-sessions")
  })

  test("keeps native mobile content clear of the bottom nav and exposes shared refresh", async () => {
    const styles = await Bun.file(new URL("./web.css", import.meta.url)).text()

    expect(styles).toContain("body.native-view-active .main-content { padding: 16px 14px calc(84px + env(safe-area-inset-bottom, 0px)); }")
    expect(styles).toContain("body.native-view-active #refresh-button { display: inline-flex; }")
  })

  test("shows CPU and memory together in machine resource rows", async () => {
    const web = await Bun.file(new URL("./web.ts", import.meta.url)).text()
    const styles = await Bun.file(new URL("./web.css", import.meta.url)).text()

    expect(web).toContain('resourceMini("CPU", cpu)')
    expect(web).toContain('resourceMini("MEM", memory)')
    expect(web).toContain("const local = Boolean(info.local)")
    expect(web).not.toContain('machine.name === "local"')
    expect(web).toContain("local ? numberValue(localSystem?.memory_percent) : numberValue(info.memory_percent)")
    expect(styles).toContain(".resource-stack")
  })

  test("keeps overview card footers pinned to the bottom of stretched dashboard rows", async () => {
    const styles = await Bun.file(new URL("./web.css", import.meta.url)).text()

    expect(styles).toContain(".attention-panel, .workloads-panel, .activity-panel { display:flex; flex-direction:column; }")
    expect(styles).toContain(".attention-panel .attention-list, .workloads-panel .workload-list, .activity-panel .activity-list { flex:1 1 auto; }")
    expect(styles).toContain(".workloads-panel .workload-list { display:flex; flex-direction:column; }")
  })

  test("renders all current alerts within the available dashboard height", async () => {
    const web = await Bun.file(new URL("./web.ts", import.meta.url)).text()
    const styles = await Bun.file(new URL("./web.css", import.meta.url)).text()
    const items = web.slice(web.indexOf("function alertItems("), web.indexOf("function metricCard("))

    expect(items).toContain("return alerts.map(")
    expect(items).not.toContain(".slice(")
    expect(web).toContain('class="attention-list" role="region" aria-label="Current alerts" tabindex="0"')
    expect(web).toContain('alertList.scrollTop = alertScrollTop')
    expect(web).toContain('if (alertFocused) alertList.focus({ preventScroll: true })')
    expect(styles).toContain(".attention-panel { height:0; min-height:100%; }")
    expect(styles).toContain(".attention-panel .attention-list { flex:1 1 0; min-height:0; overflow-y:auto;")
    expect(styles).toContain(".attention-panel .attention-list { flex:none; max-height:60vh; }")
  })

  test("uses a standalone responsive web file explorer", async () => {
    const styles = await Bun.file(new URL("./web-native.css", import.meta.url)).text()
    const files = await Bun.file(new URL("./web-native/files.ts", import.meta.url)).text()
    expect(styles).toContain(".explorer-host")
    expect(styles).toContain("@media (max-width:850px)")
    expect(styles).not.toContain(".files-layout")
    expect(files).toContain("createRoot(")
    expect(files).toContain("Filemanager")
  })

  test("keeps mobile session controls visible without shrinking the terminal after desktop refinements", async () => {
    const styles = await Bun.file(new URL("./web-native.css", import.meta.url)).text()
    const desktopRule = styles.lastIndexOf(".terminal-layout { grid-template-columns: 240px minmax(0,1fr)")
    const stackedRule = styles.lastIndexOf("@media (max-width: 850px)")
    const mobileRule = styles.lastIndexOf("@media (max-width: 720px)")
    const stackedStyles = styles.slice(stackedRule, mobileRule)

    expect(stackedRule).toBeGreaterThan(desktopRule)
    expect(stackedStyles).toContain(".terminal-layout.sidebar-hidden, .terminal-layout { display: flex; flex-direction: column; height: auto; min-height: 0; }")
    expect(stackedStyles).toContain(".terminal-sessions { display: grid; grid-template-rows: auto auto minmax(0,1fr); flex: 0 0 184px; max-height: none; }")
    expect(stackedStyles).toContain(".terminal-sessions .session-list { display: flex; align-items: flex-start;")
    expect(stackedStyles).toContain(".terminal-sessions .native-empty, .terminal-sessions .native-loading, .terminal-sessions .native-error { min-height: 0; }")
    expect(stackedStyles).toContain("overflow-x: auto; overflow-y: auto;")
    expect(stackedStyles).toContain(".terminal-stage-panel { flex: none; height: max(480px, calc(100dvh - 285px)); }")
    expect(styles.slice(mobileRule)).toContain(".terminal-stage-panel { height: max(420px, calc(100dvh - 319px)); }")
  })

  test("keeps narrow native tables compact without discarding timestamps", async () => {
    const dashboardStyles = await Bun.file(new URL("./web.css", import.meta.url)).text()
    const styles = await Bun.file(new URL("./web-native.css", import.meta.url)).text()
    const remotes = await Bun.file(new URL("./web-native/remotes.ts", import.meta.url)).text()
    const sessions = await Bun.file(new URL("./web-native/sessions.ts", import.meta.url)).text()
    const audit = await Bun.file(new URL("./web-native/audit.ts", import.meta.url)).text()

    expect(dashboardStyles).toContain(".machines-panel .table-wrap table { min-width: 700px; }")
    expect(dashboardStyles).not.toContain("  table { min-width: 700px; }")
    expect(styles).toContain(".native-table { width: 100%; min-width: 0;")
    expect(styles).toContain(".remote-table th:nth-child(1) { width: 88px; }")
    expect(styles).toContain(".remote-table th:nth-child(2) { width: auto; }")
    expect(styles).toContain(".sessions-table th:nth-child(3) { width: auto; }")
    expect(styles).toContain(".audit-page .audit-table th:nth-child(4) { width: auto; }")
    expect(styles).toContain(".sessions-table .session-mobile-updated, .audit-table .audit-mobile-time { display: block; }")
    expect(remotes).toContain('class="remote-mobile-meta"')
    expect(sessions).toContain('class="session-mobile-updated"')
    expect(audit).toContain('class="audit-mobile-time"')
  })
})
