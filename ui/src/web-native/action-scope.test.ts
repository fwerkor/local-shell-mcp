import { describe, expect, test } from "bun:test"
import { DesktopController } from "./desktop"
import { RemotesController } from "./remotes"
import { SessionsController } from "./sessions"
import { TerminalsController } from "./terminals"

// Capture the actual mounted markup, without requiring a browser DOM for the
// controllers' layout-only contract.
function markup(controller: any, overrides: string[] = []): string {
  const root: any = {
    innerHTML: "",
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    querySelector: () => null,
  }
  controller.refresh = async () => undefined
  for (const name of overrides) controller[name] = () => undefined
  controller.mount(root)
  return root.innerHTML
}

function section(html: string, start: string, end: string): string {
  const from = html.indexOf(start)
  const to = html.indexOf(end, from + start.length)
  expect(from).toBeGreaterThanOrEqual(0)
  expect(to).toBeGreaterThan(from)
  return html.slice(from, to)
}

function actions(html: string): string[] {
  return [...html.matchAll(/data-action="([^"]+)"/g)].map((match) => match[1]!)
}

describe("Native WebUI action scopes", () => {
  test("remotes separates collection invitations from actions on the selected worker", () => {
    const html = markup(new RemotesController({} as any))
    const toolbar = section(html, '<div class="native-toolbar">', '<div class="remotes-layout">')
    const detail = section(html, '<section class="native-panel remote-detail-panel">', '<div class="remote-detail"')
    expect(actions(toolbar)).toEqual(["invite"])
    expect(actions(detail)).toEqual(["rename", "reset", "revoke"])
    expect(detail).toContain('aria-label="Selected remote actions"')
    expect(detail).toContain('data-role="remote-selection"')
  })

  test("sessions separates creation, bulk selection, and single-session operations", () => {
    const html = markup(new SessionsController({} as any))
    const toolbar = section(html, '<div class="native-toolbar sessions-toolbar">', '<div class="sessions-layout">')
    const list = section(html, '<section class="native-panel sessions-list-panel">', '<section class="native-panel sessions-detail-panel">')
    const detail = section(html, '<section class="native-panel sessions-detail-panel">', '<div class="session-detail"')
    expect(actions(toolbar)).toEqual(["new-session"])
    expect(actions(list)).toEqual(["bulk-finish", "bulk-cancel", "bulk-delete", "clear-selection"])
    expect(actions(detail)).toEqual(["copy-id", "finish", "cancel", "delete"])
    expect(detail).toContain('aria-label="Selected session actions"')
  })

  test("terminals places session and view controls at their point of use", () => {
    const html = markup(new TerminalsController({ machines: () => [] } as any), ["renderMachineSelect", "showLoadingState", "initializeTerminal"])
    const toolbar = section(html, '<div class="native-toolbar terminal-toolbar">', '<div class="terminal-layout"')
    const stage = section(html, '<section class="native-panel terminal-stage-panel">', '<div class="persistent-terminal"')
    expect(actions(toolbar)).toEqual(["new-session", "toggle-sidebar"])
    expect(actions(section(stage, '<div class="terminal-connection-actions"', '<div class="terminal-view-actions"'))).toEqual(["reconnect", "kill-session"])
    expect(actions(section(stage, '<div class="terminal-view-actions"', '<div class="terminal-search"'))).toEqual(["copy", "paste", "search", "clear", "fullscreen", "font-down", "font-up"])
  })

  test("desktop keeps window discovery distinct from selected frame actions", () => {
    const html = markup(new DesktopController({} as any))
    const toolbar = section(html, '<div class="native-toolbar desktop-toolbar">', '<section class="native-panel desktop-panel">')
    const detail = section(html, '<section class="native-panel desktop-panel">', '<div class="desktop-stage-wrap">')
    expect(actions(toolbar)).toEqual(["desktop-refresh-windows"])
    expect(actions(detail)).toEqual(["desktop-scale-mode", "desktop-fullscreen", "desktop-refresh-frame"])
  })

  test("refreshing a desktop frame requires a selected window", () => {
    const controller: any = new DesktopController({} as any)
    const refresh = { disabled: false }
    controller.root = {
      querySelector: (selector: string) => selector === "[data-action=desktop-refresh-frame]" ? refresh : null,
    }
    controller.renderStatus()
    expect(refresh.disabled).toBe(true)
    controller.windows = [{ id: "window-1", title: "Test" }]
    controller.selectedWindowId = "window-1"
    controller.renderStatus()
    expect(refresh.disabled).toBe(false)
  })

  test("remote actions are disabled without a selected worker", () => {
    const controller: any = new RemotesController({} as any)
    const buttons = new Map(["rename", "reset", "revoke", "invite"].map((name) => [name, { disabled: false }]))
    controller.root = {
      querySelector: (selector: string) => buttons.get(selector.match(/data-action=(\w+)/)?.[1] || "") || null,
    }
    const priorDocument = globalThis.document
    const priorElement = globalThis.HTMLElement
    ;(globalThis as any).document = { activeElement: null }
    ;(globalThis as any).HTMLElement = class {}
    try {
      controller.render()
      expect(buttons.get("invite")?.disabled).toBe(false)
      for (const action of ["rename", "reset", "revoke"]) expect(buttons.get(action)?.disabled).toBe(true)
      controller.machines = [{ name: "worker", status: "online" }]
      controller.render()
      for (const action of ["rename", "reset", "revoke"]) expect(buttons.get(action)?.disabled).toBe(false)
      controller.enabled = false
      controller.render()
      for (const action of ["invite", "rename", "reset", "revoke"]) expect(buttons.get(action)?.disabled).toBe(true)
    } finally {
      if (priorDocument === undefined) delete (globalThis as any).document
      else globalThis.document = priorDocument
      if (priorElement === undefined) delete (globalThis as any).HTMLElement
      else globalThis.HTMLElement = priorElement
    }
  })
})
