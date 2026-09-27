import { afterEach, describe, expect, test } from "bun:test"
import { testRender } from "@opentui/react/test-utils"
import { act } from "react"
import { RemoteInviteResultDialog, RemotesScreen } from "./remotes-screen"

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

describe("RemoteInviteResultDialog", () => {
  test("keeps long join commands inside the command box without overlapping labels", async () => {
    const command =
      "curl -fsSL https://local-shell-mcp.fwerkor.eu.org/api/remote/join | bash -s -- --invite " +
      "lsmcp_inv_0123456789abcdefghijklmnopqrstuv --name build-host --workdir /workspace/project"
    const setup = await testRender(
      <RemoteInviteResultDialog
        width={100}
        invite={{
          code: "lsmcp_inv_0123456789abcdefghijklmnopqrstuv",
          command,
          expires_at: 1_800_000_000,
          join_url: "https://local-shell-mcp.fwerkor.eu.org/api/remote/join",
          ttl_s: 900,
        }}
      />,
      { width: 100, height: 26 },
    )
    renderers.push(setup.renderer)

    const reactTestGlobal = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
    reactTestGlobal.IS_REACT_ACT_ENVIRONMENT = false
    await setup.renderOnce()
    const lines = setup.captureCharFrame().split("\n")
    const inviteLine = lines.findIndex((line) => line.includes("Invite ready"))
    const instructionLine = lines.findIndex((line) => line.includes("Run this command on the remote node:"))
    const tailLine = lines.findIndex((line) => line.includes("workspace/project"))
    const expiryLine = lines.findIndex((line) => line.includes("Enter/Esc close"))

    expect(inviteLine).toBeGreaterThanOrEqual(0)
    expect(instructionLine).toBe(inviteLine + 1)
    expect(tailLine).toBeGreaterThan(instructionLine)
    expect(expiryLine).toBeGreaterThan(tailLine)
    expect(lines[tailLine]).not.toContain("└")
  })
})

describe("RemotesScreen reset confirmation", () => {
  test("submits one reset while the first confirmation request is still in flight", async () => {
    let resetCalls = 0
    let resolveReset: ((response: Response) => void) | undefined

    globalThis.fetch = ((raw: RequestInfo | URL, init?: RequestInit) => {
      const parsed = new URL(String(raw))
      if (parsed.pathname.endsWith("/api/ui/remotes") && (!init?.method || init.method === "GET")) {
        return Promise.resolve(success({
          machines: [{ name: "worker-a", status: "online", workdir: "/workspace" }],
          counts: { online: 1, offline: 0, total: 1 },
          enabled: true,
        }))
      }
      if (parsed.pathname.endsWith("/api/ui/remotes/reset") && init?.method === "POST") {
        resetCalls += 1
        return new Promise<Response>((resolve) => {
          resolveReset = resolve
        })
      }
      throw new Error(`Unexpected request: ${parsed.pathname}`)
    }) as typeof fetch

    const setup = await testRender(
      <RemotesScreen
        width={120}
        height={30}
        setStatus={() => {}}
        keyboardEnabled
        onInteractionLockChange={() => {}}
      />,
      { width: 120, height: 30 },
    )
    renderers.push(setup.renderer)

    await renderUntil(setup, () => setup.captureCharFrame().includes("worker-a"))
    await act(async () => {
      setup.mockInput.pressKey("x")
      await setup.renderOnce()
    })
    await renderUntil(setup, () => setup.captureCharFrame().includes("Reset worker-a?"))

    await act(async () => {
      setup.mockInput.pressKey("y")
      setup.mockInput.pressKey("y")
      await Promise.resolve()
    })

    expect(resetCalls).toBe(1)
    resolveReset?.(success({ cancelled_jobs: 1, preserved_jobs: 0 }))
    await renderUntil(setup, () => !setup.captureCharFrame().includes("Reset worker-a?"))
  })
})
