import { afterEach, describe, expect, test } from "bun:test"
import { testRender } from "@opentui/react/test-utils"
import { act } from "react"
import { AuditScreen } from "./audit-screen"

const originalFetch = globalThis.fetch
const renderers: Array<{ destroy: () => void }> = []

function success(data: unknown): Response {
  return new Response(JSON.stringify({ ok: true, message: "", data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })
}

async function renderUntil(
  setup: { renderOnce: () => Promise<void>; captureCharFrame: () => string },
  predicate: () => boolean,
  attempts = 30,
): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await act(async () => {
      await Promise.resolve()
      await setup.renderOnce()
    })
    if (predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
  throw new Error("Timed out waiting for OpenTUI state")
}

afterEach(() => {
  globalThis.fetch = originalFetch
  const reactTestGlobal = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
  reactTestGlobal.IS_REACT_ACT_ENVIRONMENT = false
  for (const renderer of renderers.splice(0)) renderer.destroy()
})

describe("AuditScreen pane navigation", () => {
  test("scrolls the active result pane instead of changing the selected call", async () => {
    let detailCalls = 0
    const output = Object.fromEntries(
      Array.from({ length: 40 }, (_, index) => [`result_${String(index).padStart(2, "0")}`, `value-${index}`]),
    )
    const input = Object.fromEntries(
      Array.from({ length: 40 }, (_, index) => [`request_${String(index).padStart(2, "0")}`, `value-${index}`]),
    )

    globalThis.fetch = ((raw: RequestInfo | URL) => {
      const parsed = new URL(String(raw))
      const path = parsed.pathname.replace("/api/ui", "")
      if (path === "/audit") {
        return Promise.resolve(success({
          entries: [{
            id: "call:1",
            ts: 1,
            event: "tool_call",
            node: "local",
            operation: "files",
            tool: "read",
            status: "success",
            ok: true,
            paired: true,
          }],
          count: 1,
          total_matched: 1,
        }))
      }
      if (path === "/audit/detail") {
        detailCalls += 1
        return Promise.resolve(success({
            id: "call:1",
            ts: 1,
            event: "tool_call",
            node: "local",
            operation: "files",
            tool: "read",
            status: "success",
            ok: true,
            paired: true,
            source_events: ["tool_call_start", "tool_call_end"],
            input,
          output,
        }))
      }
      throw new Error(`Unexpected request: ${parsed.pathname}${parsed.search}`)
    }) as typeof fetch

    const setup = await testRender(
      <AuditScreen
        machines={[{ name: "local", status: "online" }]}
        width={180}
        height={34}
        setStatus={() => {}}
        keyboardEnabled
        onInteractionLockChange={() => {}}
      />,
      { width: 180, height: 34 },
    )
    renderers.push(setup.renderer)

    await renderUntil(
      setup,
      () => detailCalls >= 1 && setup.captureCharFrame().includes("result_00"),
    )

    await act(async () => {
      setup.mockInput.pressTab()
      await setup.renderOnce()
    })
    await renderUntil(setup, () => setup.captureCharFrame().includes("j scroll down"))
    for (let index = 0; index < 12; index += 1) {
      await act(async () => {
        setup.mockInput.pressKey("j")
        await setup.renderOnce()
      })
    }

    const scrolled = setup.captureCharFrame()
    expect(scrolled).not.toContain("result_00")
    expect(scrolled).toContain("result_12")
    expect(scrolled).toContain("read")
  })
})
