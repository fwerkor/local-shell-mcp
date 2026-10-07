import { describe, expect, test } from "bun:test"

describe("WebUI overview", () => {
  test("omits the machine capabilities column", async () => {
    const web = await Bun.file(new URL("./web.ts", import.meta.url)).text()
    const start = web.indexOf("function machineRows")
    const end = web.indexOf("function workloadIdentity")
    const machineTable = web.slice(start, end)

    expect(start).toBeGreaterThanOrEqual(0)
    expect(end).toBeGreaterThan(start)
    expect(machineTable).not.toContain("<th>Capabilities</th>")
    expect(machineTable).not.toContain("capabilities.map")
    expect(machineTable).toContain('colspan="4"')
    expect(machineTable).toContain("const local = Boolean(info.local)")
    expect(machineTable).not.toContain('machine.name === "local"')
  })
})
