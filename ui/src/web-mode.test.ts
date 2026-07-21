import { describe, expect, test } from "bun:test"
import { hashForView, interfaceModeForView, oauthReturnView, viewFromHash } from "./web-mode"

describe("WebUI mode routing", () => {
  test("parses native WebUI and OpenTUI routes", () => {
    expect(viewFromHash("#/overview")).toBe("overview")
    expect(viewFromHash("#machines")).toBe("machines")
    expect(viewFromHash("#/console/")).toBe("console")
  })

  test("supports explicit interface aliases", () => {
    expect(viewFromHash("#/web")).toBe("overview")
    expect(viewFromHash("#/dashboard")).toBe("overview")
    expect(viewFromHash("#/tui")).toBe("console")
    expect(viewFromHash("#/opentui")).toBe("console")
  })

  test("rejects unknown routes and emits canonical hashes", () => {
    expect(viewFromHash("")).toBeNull()
    expect(viewFromHash("#/unknown")).toBeNull()
    expect(hashForView("todos")).toBe("#/todos")
  })

  test("maps views to the corresponding interface", () => {
    expect(interfaceModeForView("overview")).toBe("web")
    expect(interfaceModeForView("activity")).toBe("web")
    expect(interfaceModeForView("console")).toBe("tui")
  })

  test("preserves compatible bookmarks without overriding an explicit interface choice", () => {
    expect(oauthReturnView("#/todos", "overview")).toBe("todos")
    expect(oauthReturnView("#/console", "overview")).toBe("overview")
    expect(oauthReturnView("#/overview", "console")).toBe("console")
  })
})
