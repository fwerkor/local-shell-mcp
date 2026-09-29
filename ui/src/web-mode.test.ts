import { describe, expect, test } from "bun:test"
import { hashForView, interfaceModeForView, oauthReturnView, viewFromHash } from "./web-mode"

describe("WebUI mode routing", () => {
  test("parses native WebUI and OpenTUI routes", () => {
    expect(viewFromHash("#/overview")).toBe("overview")
    expect(viewFromHash("#/files")).toBe("files")
    expect(viewFromHash("#/terminals")).toBe("terminals")
    expect(viewFromHash("#/desktop")).toBe("desktop")
    expect(viewFromHash("#/sessions")).toBe("sessions")
    expect(viewFromHash("#/remotes")).toBe("remotes")
    expect(viewFromHash("#/audit")).toBe("audit")
    expect(viewFromHash("#/workloads")).toBe("workloads")
    expect(viewFromHash("#/activity")).toBe("activity")
    expect(viewFromHash("#/console/")).toBe("console")
  })

  test("supports explicit interface aliases", () => {
    expect(viewFromHash("#/web")).toBe("overview")
    expect(viewFromHash("#/dashboard")).toBe("overview")
    expect(viewFromHash("#/machines")).toBe("remotes")
    expect(viewFromHash("#/tui")).toBe("console")
    expect(viewFromHash("#/opentui")).toBe("console")
  })

  test("rejects unknown routes and emits canonical hashes", () => {
    expect(viewFromHash("")).toBeNull()
    expect(viewFromHash("#/unknown")).toBeNull()
    expect(hashForView("audit")).toBe("#/audit")
  })

  test("maps views to the corresponding interface", () => {
    expect(interfaceModeForView("overview")).toBe("web")
    expect(interfaceModeForView("audit")).toBe("web")
    expect(interfaceModeForView("console")).toBe("tui")
  })

  test("preserves compatible bookmarks without overriding an explicit interface choice", () => {
    expect(oauthReturnView("#/audit", "overview")).toBe("audit")
    expect(oauthReturnView("#/console", "overview")).toBe("overview")
    expect(oauthReturnView("#/overview", "console")).toBe("console")
  })
})
