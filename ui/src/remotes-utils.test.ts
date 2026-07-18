import { describe, expect, test } from "bun:test"
import { remoteSystemInfo, remoteVersion } from "./remotes-utils"
import type { Machine } from "./types"

function machine(info?: Record<string, unknown>): Machine {
  return { name: "worker", status: "online", info }
}

describe("remote metadata", () => {
  test("formats the worker runtime version", () => {
    expect(remoteVersion(machine({ lsm_version: "3.0.4" }))).toBe("3.0.4")
    expect(remoteVersion(machine())).toBe("—")
    expect(remoteVersion(machine({ lsm_version: 304 }))).toBe("—")
  })

  test("keeps the version out of the generic system information block", () => {
    expect(remoteSystemInfo(machine({ hostname: "node", lsm_version: "3.0.4" }))).toEqual({
      hostname: "node",
    })
  })
})
