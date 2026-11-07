import { describe, expect, test } from "bun:test"
import { nextRestartSettings, restartDestination } from "./settings"

describe("Controller Settings restart reconnect", () => {
  test("uses running server port even after the saved port changes", () => {
    expect(restartDestination("http://127.0.0.1:8765/ui/#/settings", 8765, 8899, "/ui"))
      .toBe("http://127.0.0.1:8899/ui/#/settings")
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
