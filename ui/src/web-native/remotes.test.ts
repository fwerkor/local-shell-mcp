import { describe, expect, test } from "bun:test"
import { renderRemoteDetail } from "./remotes"
import type { Machine } from "../types"

function worker(overrides: Partial<Machine> = {}): Machine {
  return {
    name: "build-host",
    status: "online",
    workdir: "/workspace",
    queue_depth: 2,
    reset_generation: 3,
    capabilities: ["shell", "persistent_shell", "jobs", "files", "gui"],
    info: {
      lsm_version: "5.1.4",
      platform: "linux",
      cpu_count: 192,
      cpu_percent: 10.3,
      memory_used_bytes: 16 * 1024 ** 3,
      memory_total_bytes: 128 * 1024 ** 3,
      memory_percent: 12.5,
    },
    ...overrides,
  }
}

describe("Native WebUI remote details", () => {
  test("shows useful node and resource facts instead of static capability badges", () => {
    const html = renderRemoteDetail(worker())
    expect(html).toContain("build-host")
    expect(html).toContain("5.1.4")
    expect(html).toContain("/workspace")
    expect(html).toContain("<dt>Queue</dt><dd>2</dd>")
    expect(html).toContain("<dt>Platform</dt><dd>Linux</dd>")
    expect(html).toContain("192 logical CPUs · 10.3%")
    expect(html).toContain("16 GiB / 128 GiB · 12.5%")
    expect(html).not.toContain("Capabilities")
    expect(html).not.toContain("persistent_shell")
    expect(html).not.toContain('<span class="tag">')
  })

  test("keeps raw system info and reset generation behind closed native details", () => {
    const html = renderRemoteDetail(worker())
    expect(html).toContain('<details class="detail-json" data-role="remote-diagnostics">')
    expect(html).toContain("<summary>Advanced diagnostics</summary>")
    expect(html).not.toContain('data-role="remote-diagnostics" open')
    expect(html).toContain("Reset generation")
    expect(html).toContain("Raw system information")
    expect(html).toContain("cpu_count")
  })

  test("labels offline telemetry as last reported and handles missing resource data", () => {
    const html = renderRemoteDetail(worker({ status: "offline", info: {} }))
    expect(html).toContain("Last reported resources")
    expect(html).toContain("No resource data reported")
    expect(html).not.toContain("logical CPUs")
    expect(html).not.toContain("<dt>Memory</dt>")
  })

  test("ignores invalid metrics but supports partially reported values", () => {
    const html = renderRemoteDetail(worker({ info: {
      cpu_count: null,
      cpu_percent: 200,
      memory_total_bytes: 2 * 1024 ** 4,
      memory_percent: 5.2,
    } }))
    expect(html).not.toContain("<dt>CPU</dt>")
    expect(html).toContain("2 TiB total · 5.2%")
  })

  test("escapes arbitrary worker-supplied values", () => {
    const html = renderRemoteDetail(worker({
      name: "<img onerror=alert(1)>",
      workdir: "<script>",
      info: { platform: "<svg onload=alert(2)>" },
    }))
    expect(html).not.toContain("<img")
    expect(html).not.toContain("<script>")
    expect(html).not.toContain("<svg")
    expect(html).toContain("&lt;script&gt;")
    expect(html).toContain("&lt;svg")
  })
})
