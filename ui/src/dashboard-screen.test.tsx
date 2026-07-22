import { afterEach, describe, expect, test } from "bun:test"
import { testRender } from "@opentui/react/test-utils"
import { act, useState } from "react"
import { Alerts, MinimalDashboard } from "./dashboard-screen"
import type { DashboardAlert, DashboardPayload } from "./types"

const renderers: Array<{ destroy: () => void }> = []

const reportedAlerts: DashboardAlert[] = [
  {
    severity: "warning",
    title: "Job release-v3.1.0-watch lost",
    detail: "job session exited without a completion record",
    age_s: 4_860,
  },
  {
    severity: "error",
    title: "Job pr96-coverage-fix failed",
    detail: "export PYTHONPATH=/workspace/lsm-transfer-clean-test/src",
  },
  {
    severity: "error",
    title: "Job lsm-transfer-clean-full-tests failed",
    detail: "export PYTHONPATH=/workspace/lsm-transfer-clean-test/src",
  },
  {
    severity: "warning",
    title: "14 recent MCP call failure(s)",
    detail: "Open Audit for call inputs and returned errors",
  },
]

function destroyRenderer(renderer: { destroy: () => void }) {
  const reactTestGlobal = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
  reactTestGlobal.IS_REACT_ACT_ENVIRONMENT = false
  renderer.destroy()
}

function populatedPanelLines(frame: string): string[] {
  const lines = frame.split("\n")
  if (lines.at(-1) === "") lines.pop()
  return lines
    .slice(1, -1)
    .map((line) => line.slice(1, -1).trim())
    .filter(Boolean)
}

afterEach(() => {
  for (const renderer of renderers.splice(0)) destroyRenderer(renderer)
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

  test("normalizes terminal control characters before rendering alerts", async () => {
    const setup = await testRender(
      <Alerts
        alerts={[{
          severity: "warning",
          title: "\u001b]8;;https://example.test\u0007Job coverage-fix\u001b]8;;\u0007\rfailed\u009b31m now\u009b0m",
          detail: "set -euo\tpipefail\r\n\u001bPprivate metadata\u001b\\export PYTHONPATH=/workspace/src",
        }]}
        width={58}
        rows={1}
      />,
      { width: 58, height: 6 },
    )
    renderers.push(setup.renderer)

    await act(async () => setup.renderOnce())
    const frame = setup.captureCharFrame()
    const populated = populatedPanelLines(frame)

    expect(frame).not.toContain("\u001b")
    expect(populated).toContainEqual(expect.stringContaining("WARN  Job coverage-fix failed now"))
    expect(populated).toContainEqual(expect.stringContaining("set -euo pipefail export PYTHONPATH=/workspace/src"))
    expect(populated.filter((line) => line.includes("Job coverage-fix"))).toHaveLength(1)
    expect(frame).not.toContain("example.test")
    expect(frame).not.toContain("private metadata")
  })

  test("normalizes alert text in the minimal dashboard", async () => {
    const payload = {
      alerts: [{
        severity: "warning",
        title: "\u001b]8;;https://example.test\u0007Job compact\u001b]8;;\u0007\rfailed",
      }],
      jobs: [],
      sessions: [],
      job_counts: {},
      system: { cpu_percent: 1, memory_percent: 2, disk_percent: 3 },
    } as unknown as DashboardPayload
    const setup = await testRender(<MinimalDashboard payload={payload} width={60} />, {
      width: 60,
      height: 12,
    })
    renderers.push(setup.renderer)

    await act(async () => setup.renderOnce())
    const frame = setup.captureCharFrame()

    expect(frame).toContain("! Job compact failed")
    expect(frame).not.toContain("example.test")
    expect(frame).not.toContain("\u001b")
  })

  test("keeps alert rows isolated across narrow, regular, and wide panels", async () => {
    const dimensions = [
      { width: 24, rows: 1 },
      { width: 28, rows: 2 },
      { width: 32, rows: 4 },
      { width: 33, rows: 3 },
      { width: 34, rows: 1 },
      { width: 35, rows: 2 },
      { width: 36, rows: 4 },
      { width: 38, rows: 3 },
      { width: 40, rows: 4 },
      { width: 42, rows: 2 },
      { width: 44, rows: 4 },
      { width: 48, rows: 3 },
      { width: 52, rows: 4 },
      { width: 58, rows: 4 },
      { width: 64, rows: 4 },
      { width: 72, rows: 4 },
      { width: 96, rows: 4 },
    ]

    for (const { width, rows } of dimensions) {
      const detailRows = width >= 34 ? 1 : 0
      const shown = Math.min(rows, reportedAlerts.length)
      const hasOverflow = shown < reportedAlerts.length
      const height = 4 + shown * (1 + detailRows) + (hasOverflow ? 1 : 0)
      const setup = await testRender(<Alerts alerts={reportedAlerts} width={width} rows={rows} />, {
        width,
        height,
      })
      try {
        await act(async () => setup.renderOnce())
        const frame = setup.captureCharFrame()
        const lines = frame.split("\n")
        if (lines.at(-1) === "") lines.pop()
        const populated = populatedPanelLines(frame)

        expect(lines.every((line) => Array.from(line).length === width)).toBe(true)
        expect(populated).toHaveLength(shown * (1 + detailRows) + (hasOverflow ? 1 : 0))
        for (let index = 0; index < shown; index += 1) {
          const titleLine = populated[index * (1 + detailRows)]!
          expect(titleLine).toMatch(/^(WARN|ERRO)  /)
          if (detailRows) {
            const detailLine = populated[index * 2 + 1]!
            expect(detailLine).not.toMatch(/^(WARN|ERRO)  /)
            expect(detailLine).not.toContain(" failed")
          }
        }
        if (hasOverflow) expect(populated.at(-1)).toBe(`+${reportedAlerts.length - shown} more alerts`)
      } finally {
        destroyRenderer(setup.renderer)
      }
    }
  })

  test("clears prior alert text after repeated live updates", async () => {
    const sequences: DashboardAlert[][] = [
      [
        { severity: "warning", title: "OLD-A failed", detail: "old-detail-alpha" },
        { severity: "warning", title: "OLD-B failed", detail: "old-detail-beta" },
      ],
      [
        { severity: "error", title: "NEW-A failed", detail: "new-detail-alpha" },
        { severity: "error", title: "NEW-B failed", detail: "new-detail-beta" },
        { severity: "warning", title: "NEW-C lost", detail: "new-detail-gamma" },
      ],
      [{ severity: "warning", title: "FINAL alert", detail: "final-detail" }],
      reportedAlerts,
    ]

    for (const width of [34, 36, 40, 48, 58, 72]) {
      let replaceAlerts = (_alerts: DashboardAlert[]) => {}
      function Harness() {
        const [alerts, setAlerts] = useState(sequences[0]!)
        replaceAlerts = setAlerts
        return <Alerts alerts={alerts} width={width} rows={4} />
      }

      const setup = await testRender(<Harness />, { width, height: 14 })
      try {
        await act(async () => setup.renderOnce())

        for (const alerts of sequences.slice(1)) {
          act(() => replaceAlerts(alerts))
          await act(async () => setup.renderOnce())
          const frame = setup.captureCharFrame()
          const populated = populatedPanelLines(frame)
          expect(frame).not.toContain("OLD-A")
          expect(frame).not.toContain("OLD-B")
          expect(frame).not.toContain("old-detail")
          expect(populated.every((line) => !line.includes("detail") || !line.includes("  Job"))).toBe(true)
          expect(populated.filter((line) => /^(WARN|ERRO)  /.test(line))).toHaveLength(Math.min(4, alerts.length))
        }
      } finally {
        destroyRenderer(setup.renderer)
      }
    }
  })
})
