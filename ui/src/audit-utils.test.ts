import { describe, expect, test } from "bun:test"
import {
  AUDIT_OPERATIONS,
  auditListLayout,
  auditStackedVisibleRows,
  auditInput,
  auditOutput,
  fitAuditColumn,
  formatAuditValue,
  selectionAfterRefresh,
} from "./audit-utils"
import type { AuditEntry } from "./types"

function entry(id: string, ts: number): AuditEntry {
  return {
    id,
    ts,
    event: "mcp_tool_call",
    node: "local",
    operation: "files",
    tool: "read_file",
  }
}

describe("audit selection", () => {
  test("keeps following the newest record when the first row is selected", () => {
    expect(selectionAfterRefresh([entry("a", 2)], 0, [entry("b", 3), entry("a", 2)])).toBe(0)
  })

  test("preserves a non-top selected record when new rows arrive", () => {
    const previous = [entry("a", 2), entry("b", 1)]
    const next = [entry("c", 3), entry("a", 2), entry("b", 1)]
    expect(selectionAfterRefresh(previous, 1, next)).toBe(2)
  })
})

describe("audit formatting", () => {
  test("shows only useful data from the standard tool envelope", () => {
    expect(
      formatAuditValue({ ok: true, message: "", data: { path: "a.txt", machine: null } }, "empty"),
    ).toBe('{\n  "path": "a.txt"\n}')
  })

  test("uses keyword arguments as call input and result as call output", () => {
    const call: AuditEntry = {
      ...entry("call", 1),
      arguments: { positional_count: 0, keyword_args: { path: "a.txt", machine: null } },
      result: { ok: true, message: "", data: { bytes: 4 } },
    }
    expect(auditInput(call)).toEqual({ path: "a.txt", machine: null })
    expect(auditOutput(call)).toEqual({ ok: true, message: "", data: { bytes: 4 } })
  })

  test("includes semantic child events alongside the public result", () => {
    const call: AuditEntry = {
      ...entry("call", 1),
      output: { ok: true, message: "", data: { revoked: true } },
      related_events: [{ event: "download_link_revoked", path: "/tmp/report.txt" }],
    }
    expect(auditOutput(call)).toEqual({
      result: { revoked: true },
      related_events: [{ event: "download_link_revoked", path: "/tmp/report.txt" }],
    })
  })
})

describe("audit wide layout", () => {
  test("caps the list pane and leaves the majority of a wide screen to details", () => {
    const layout = auditListLayout([
      {
        ...entry("wide", 1),
        node: "remote-worker-123456",
        operation: "transfer",
        tool: "playwright_run_script_tool",
      },
    ], 198)

    expect(layout.paneWidth).toBeLessThanOrEqual(86)
    expect(198 - layout.paneWidth - 1).toBeGreaterThan(layout.paneWidth)
  })

  test("keeps ordinary node, operation, and tool names intact on wide screens", () => {
    const call = {
      ...entry("wide", 1),
      node: "remote-worker-123456",
      operation: "transfer",
      tool: "playwright_run_script_tool",
    }
    const layout = auditListLayout([call], 198)

    expect(fitAuditColumn(call.node, layout.nodeWidth).trimEnd()).toBe(call.node)
    expect(fitAuditColumn(call.operation, layout.operationWidth).trimEnd()).toBe(call.operation)
    expect(fitAuditColumn(call.tool, layout.toolWidth).trimEnd()).toBe(call.tool)
  })

  test("preserves the minimum detail width at the horizontal breakpoint", () => {
    const layout = auditListLayout([entry("compact", 1)], 110)
    expect(110 - layout.paneWidth - 1).toBeGreaterThanOrEqual(44)
  })
})

describe("audit stacked layout", () => {
  test("limits records to the rows above the detail panel", () => {
    expect(auditStackedVisibleRows(37, 15, false)).toBe(9)
  })

  test("accounts for the active filter summary", () => {
    expect(auditStackedVisibleRows(37, 15, true)).toBe(6)
  })
})

test("operation filters match the compact current tool groups", () => {
  expect(AUDIT_OPERATIONS).toEqual([
    "",
    "files",
    "shell",
    "jobs",
    "transfer",
    "browser",
    "remote",
    "agent",
  ])
})
