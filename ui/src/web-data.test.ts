import { describe, expect, test } from "bun:test"

import { activeJobCount, visibleWorkloadCount } from "./web-data"

describe("native WebUI data mapping", () => {
  test("counts visible jobs and standalone sessions without double-counting job sessions", () => {
    expect(visibleWorkloadCount({ jobs: [{}], sessions: [{}] })).toBe(2)
  })

})

describe("active job metric", () => {
  test("includes starting, running, stopping and retrying jobs", () => {
    expect(activeJobCount({ job_counts: { starting: 2, running: 3, stopping: 4, retrying: 5, completed: 100, failed: 20 } })).toBe(14)
    expect(activeJobCount({ job_counts: { starting: 1, retrying: 2 } })).toBe(3)
  })
  test("falls back to the backend active list when counts are absent", () => {
    expect(activeJobCount({ jobs: [{}, {}] })).toBe(2)
    expect(activeJobCount({})).toBe(0)
  })
})
