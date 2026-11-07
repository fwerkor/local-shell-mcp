import { describe, expect, test } from "bun:test"
import { nextRestartSettings, restartDestination, SettingsController } from "./settings"
import type { NativePageContext } from "./common"

describe("Controller Settings restart reconnect", () => {
  test("uses running server port even after the saved port changes", () => {
    expect(restartDestination("http://127.0.0.1:8765/ui/#/settings", 8765, 8899, "/ui"))
      .toBe("http://127.0.0.1:8899/ui/#/settings")
  })
  test("changes implicit default HTTP and HTTPS listener ports", () => {
    expect(restartDestination("http://127.0.0.1:80/ui/#/settings", 80, 8080, "/ui"))
      .toBe("http://127.0.0.1:8080/ui/#/settings")
    expect(restartDestination("https://127.0.0.1:443/ui/#/settings", 443, 8443, "/ui"))
      .toBe("https://127.0.0.1:8443/ui/#/settings")
  })
  test("preserves externally mapped reverse proxy port", () => {
    expect(restartDestination("https://control.example.com:443/ui/#/settings", 8765, 8899, "/ui"))
      .toBe("https://control.example.com/ui/#/settings")
    expect(restartDestination("https://control.example.com:9443/ui/#/settings", 8765, 8899, "/ui"))
      .toBe("https://control.example.com:9443/ui/#/settings")
  })
  test("uses the freshly loaded settings after a saved value is reset", () => {
    const running = { port: 8765, ui_path: "/ui" }
    const saved = nextRestartSettings({ running, fields: [
      { name: "port", value: 8899 }, { name: "ui_path", value: "/custom" },
    ] } as Parameters<typeof nextRestartSettings>[0])
    expect(restartDestination("http://127.0.0.1:8765/ui/#/settings", running.port, saved.port, saved.uiPath))
      .toBe("http://127.0.0.1:8899/custom/#/settings")
    const reset = nextRestartSettings({ running, fields: [
      { name: "port", value: 8765 }, { name: "ui_path", value: "/ui" },
    ] } as Parameters<typeof nextRestartSettings>[0])
    expect(restartDestination("http://127.0.0.1:8765/ui/#/settings", running.port, reset.port, reset.uiPath))
      .toBe("http://127.0.0.1:8765/ui/#/settings")
  })
  test("updates the UI path while preserving the view hash", () => {
    expect(restartDestination("http://127.0.0.1:8765/ui/#/settings", 8765, 8765, "/app"))
      .toBe("http://127.0.0.1:8765/app/#/settings")
  })
})


describe("Controller Settings authorization recovery", () => {
  test("offers reauthorization on missing admin scope and executes the action", async () => {
    const calls: string[] = []
    const context: NativePageContext = {
      api: {
        get: async () => { throw new Error("OAuth token is missing required scope(s): admin:config") },
        send: async () => undefined as never,
      },
      uiPath: "/ui",
      accessToken: () => "old-token",
      machines: () => [],
      notify: () => undefined,
      refreshChrome: async () => undefined,
      reauthorize: () => { calls.push("reauthorize") },
    }
    const root = {
      innerHTML: "",
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }
    const controller = new SettingsController(context) as unknown as {
      mount: (root: HTMLElement) => void
      onClick: (event: Event) => Promise<void>
    }
    controller.mount(root as unknown as HTMLElement)
    await Bun.sleep(0)
    expect(root.innerHTML).toContain('data-action="reauthorize"')

    const previousElement = globalThis.Element
    class ButtonElement {
      closest(selector: string) {
        return selector === "[data-action]" ? { dataset: { action: "reauthorize" } } : null
      }
    }
    ;(globalThis as unknown as { Element: unknown }).Element = ButtonElement
    try {
      await controller.onClick({ target: new ButtonElement() } as unknown as Event)
      expect(calls).toEqual(["reauthorize"])
    } finally {
      ;(globalThis as unknown as { Element: unknown }).Element = previousElement
    }
  })
})
