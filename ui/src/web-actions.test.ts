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

    for (const source of [files, sessions, remotes]) {
      expect(source).toContain('this.listen(root, "keydown"')
      expect(source).toContain('tabindex="${selected ? "0" : "-1"}"')
      expect(source).toContain('event.key === "ArrowDown"')
      expect(source).toContain('event.key === "Enter"')
    }
    expect(sessions).toContain("data-session-id")
    expect(remotes).toContain("data-remote-name")
    expect(remotes).toContain("focusedName")
    expect(files).toContain("this.select(entryPath, true)")
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

    expect(files).toContain('"open"')
    expect(files).toContain('data-action="parent"')
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

  test("uses the shared WebUI refresh control instead of duplicating it inside native pages", async () => {
    const sources = await Promise.all(
      nativePages.map((page) => Bun.file(new URL(`./web-native/${page}.ts`, import.meta.url)).text()),
    )

    for (const source of sources) expect(source).not.toContain('button("Refresh"')
    expect(sources.join("\n")).not.toContain("refresh-sessions")
  })

  test("keeps native mobile content clear of the bottom nav and exposes shared refresh", async () => {
    const styles = await Bun.file(new URL("./web.css", import.meta.url)).text()

    expect(styles).toContain("body.native-view-active .main-content { padding: 16px 14px 84px; }")
    expect(styles).toContain("body.native-view-active #refresh-button { display: inline-flex; }")
  })

  test("uses two visible file panes after the machine rail is hidden", async () => {
    const styles = await Bun.file(new URL("./web-native.css", import.meta.url)).text()
    const compactRule = styles.lastIndexOf("@media (max-width: 1100px)")
    const narrowRule = styles.lastIndexOf("@media (max-width: 850px)")
    const compactStyles = styles.slice(compactRule, narrowRule)

    expect(compactRule).toBeGreaterThan(styles.lastIndexOf("@media (max-width: 1200px)"))
    expect(compactStyles).toContain(".files-layout, .files-layout.no-parent { grid-template-columns: minmax(0,1fr); }")
    expect(compactStyles).toContain(".files-layout.preview-open, .files-layout.no-parent.preview-open { grid-template-columns: minmax(360px,1fr) minmax(280px,.65fr); }")
  })
})
