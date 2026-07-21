import { describe, expect, test } from "bun:test"

import { todoTitle, visibleWorkloadCount } from "./web-data"

describe("native WebUI data mapping", () => {
  test("counts visible jobs and standalone sessions without double-counting job sessions", () => {
    expect(visibleWorkloadCount({ jobs: [{}], sessions: [{}] })).toBe(2)
  })

  test("uses the persisted todo content field", () => {
    expect(todoTitle({ content: "review PR 94", status: "pending" })).toBe("review PR 94")
    expect(todoTitle({})).toBe("Untitled todo")
  })
})
