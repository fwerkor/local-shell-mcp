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

  test("does not let a long detail hide its title row", async () => {
    const alerts: DashboardAlert[] = [
      {
        severity: "warning",
        title: "Job package-wait active",
        detail: "while pgrep -x apt-get >/dev/null || pgrep -x dpkg >/dev/null; do sleep 5; done",
      },
      {
        severity: "warning",
        title: "Job release-v3.0.8-watch lost",
        detail: "job session exited without a completion record · 12h 8m",
      },
      {
        severity: "warning",
        title: "Job release-v3.0.8 lost",
        detail: "job session exited without a completion record · 14h 20m",
      },
      {
        severity: "warning",
        title: "18 recent MCP call failure(s)",
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

    expect(lines).toContainEqual(expect.stringContaining("WARN  Job package-wait active"))
    expect(lines).toContainEqual(expect.stringContaining("while pgrep -x apt-get"))
    expect(lines.filter((line) => line.includes("while pgrep -x apt-get"))).toHaveLength(1)
    expect(lines).toContainEqual(expect.stringContaining("WARN  Job release-v3.0.8-watch lost"))
    expect(lines).toContainEqual(expect.stringContaining("WARN  Job release-v3.0.8 lost"))
    expect(lines).toContainEqual(expect.stringContaining("WARN  18 recent MCP call failure(s)"))
  })
})
