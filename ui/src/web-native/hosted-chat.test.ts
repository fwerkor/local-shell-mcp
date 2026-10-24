import { expect, test } from "bun:test"
import { HostedChatController } from "./hosted-chat"

test("late model-update response never switches back to an earlier conversation", async () => {
  const controller: any = new HostedChatController({} as any)
  let resolveUpdate!: (record: any) => void
  controller.active = { id: "chat-a", profile_id: "old", status: "idle" }
  controller.post = () => new Promise((resolve) => { resolveUpdate = resolve })
  controller.renderConversation = () => undefined
  const pending = controller.changeModel("new")
  controller.active = { id: "chat-b", profile_id: "other", status: "idle" }
  resolveUpdate({ id: "chat-a", profile_id: "new", status: "idle" })
  await pending
  expect(controller.active.id).toBe("chat-b")
  expect(controller.active.profile_id).toBe("other")
})

test("model-update response still updates the active conversation", async () => {
  const controller: any = new HostedChatController({} as any)
  controller.active = { id: "chat-a", profile_id: "old", status: "idle" }
  controller.post = async () => ({ id: "chat-a", profile_id: "new", status: "idle" })
  controller.renderConversation = () => undefined
  await controller.changeModel("new")
  expect(controller.active.profile_id).toBe("new")
})
