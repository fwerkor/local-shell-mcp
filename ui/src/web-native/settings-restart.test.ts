import { describe, expect, test } from "bun:test"
import { restartDestination } from "./settings"

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
  test("updates the UI path while preserving the view hash", () => {
    expect(restartDestination("http://127.0.0.1:8765/ui/#/settings", 8765, 8765, "/app"))
      .toBe("http://127.0.0.1:8765/app/#/settings")
  })
})
