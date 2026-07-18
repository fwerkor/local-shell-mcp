import { describe, expect, test } from "bun:test"
import {
  AUDIT_OPERATIONS,
  auditInput,
  auditOutput,
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
