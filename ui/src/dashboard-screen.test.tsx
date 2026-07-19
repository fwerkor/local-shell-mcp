import { afterEach, describe, expect, test } from "bun:test"
import { testRender } from "@opentui/react/test-utils"
import { Alerts } from "./dashboard-screen"
import type { DashboardAlert } from "./types"

const renderers: Array<{ destroy: () => void }> = []

afterEach(() => {
  for (const renderer of renderers.splice(0)) renderer.destroy()
})

describe("Dashboard alerts", () => {
  test("renders titles and details on separate terminal rows", async () => {
    const alerts: DashboardAlert[] = [
      {
        severity: "warning",
        title: "Job fixed-nju-cli-3 failed",
        detail: "set -euo pipefail",
      },
      {
        severity: "warning",
        title: "Job fixed-nju-cli-2 failed",
        detail: "export CARGO_HOME=/workspace/.cargo",
      },
      {
        severity: "warning",
        title: "Job fixed-nju-cli failed",
        detail: "rustup toolchain install stable --profile minimal",
      },
      {
        severity: "warning",
        title: "1 recent MCP call failure(s)",
        detail: "Open Audit for call inputs and returned errors",
      },
    ]
    const setup = await testRender(<Alerts alerts={alerts} width={58} rows={4} />, {
      width: 58,
      height: 14,
    })
    renderers.push(setup.renderer)

    const reactTestGlobal = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
    reactTestGlobal.IS_REACT_ACT_ENVIRONMENT = false
    await setup.renderOnce()
    const lines = setup.captureCharFrame().split("\n")

    expect(lines).toContainEqual(expect.stringContaining("WARN  Job fixed-nju-cli-3 failed"))
    expect(lines).toContainEqual(expect.stringContaining("set -euo pipefail"))
    expect(lines).toContainEqual(expect.stringContaining("WARN  Job fixed-nju-cli-2 failed"))
    expect(lines).toContainEqual(expect.stringContaining("export CARGO_HOME=/workspace/.cargo"))
    expect(lines).toContainEqual(expect.stringContaining("WARN  Job fixed-nju-cli failed"))
    expect(lines).toContainEqual(expect.stringContaining("rustup toolchain install stable --profile minimal"))
    expect(lines).toContainEqual(expect.stringContaining("WARN  1 recent MCP call failure(s)"))
    expect(lines).toContainEqual(expect.stringContaining("Open Audit for call inputs and returned errors"))
  })
})
