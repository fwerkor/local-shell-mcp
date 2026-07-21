import { afterEach, describe, expect, test } from "bun:test"
import { testRender } from "@opentui/react/test-utils"
import { RemoteInviteResultDialog } from "./remotes-screen"

const renderers: Array<{ destroy: () => void }> = []

afterEach(() => {
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
