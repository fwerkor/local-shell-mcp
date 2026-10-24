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

test("archived browser is separate and does not search live conversations", async () => {
  const controller: any = new HostedChatController({} as any)
  const nodes = new Map<string, any>()
  const node = (selector: string) => {
    if (!nodes.has(selector)) nodes.set(selector, { innerHTML: "", textContent: "", hidden: false, value: "", disabled: false })
    return nodes.get(selector)
  }
  controller.root = { querySelector: node }
  controller.get = async (action: string) => {
    if (action === "profiles") return [{ id: "p_1", name: "Profile", model: "model" }]
    if (action === "conversations") return [{ id: "live", title: "Normal session", status: "idle", profile_id: "p_1" }]
    if (action === "archives") return [{ id: "archived", title: "Research archive", status: "idle", profile_id: "p_1" }]
    throw new Error(action)
  }
  controller.select = async (id: string) => { controller.active = { id } }
  controller.renderConversation = () => undefined
  controller.closeWorkspace = async () => undefined
  await controller.reload()
  expect(node("[data-chat-list]").innerHTML).toContain("Normal session")
  expect(node("[data-chat-list]").innerHTML).not.toContain("Research archive")
  await controller.action("archives")
  expect(controller.showArchives).toBe(true)
  expect(node("[data-chat-list]").innerHTML).toContain("Research archive")
  expect(node("[data-chat-list]").innerHTML).not.toContain("Normal session")
  expect(node('[data-chat-action="new"]').hidden).toBe(true)
  controller.archiveFilter = "unrelated"
  controller.renderList()
  expect(node("[data-chat-list]").innerHTML).not.toContain("Research archive")
  controller.archiveFilter = "research"
  controller.renderList()
  expect(node("[data-chat-list]").innerHTML).toContain("Research archive")
  await controller.action("archives")
  expect(node("[data-chat-list]").innerHTML).toContain("Normal session")
})

test("archive and restore actions use distinct endpoints and preserve conversation id", async () => {
  const controller: any = new HostedChatController({} as any)
  const calls: string[] = []
  const selected: string[] = []
  controller.active = { id: "chat-1", status: "idle", profile_id: "p_1" }
  controller.post = async (action: string) => { calls.push(action); return {} }
  controller.closeWorkspace = async () => undefined
  controller.reload = async () => undefined
  controller.select = async (id: string) => { selected.push(id) }
  await controller.action("archive")
  expect(calls).toEqual(["conversation-archive"])
  expect(controller.active).toBeNull()
  controller.showArchives = true
  controller.active = { id: "chat-1", status: "idle", profile_id: "p_1" }
  await controller.action("restore")
  expect(calls).toEqual(["conversation-archive", "conversation-restore"])
  expect(controller.showArchives).toBe(false)
  expect(selected).toEqual(["chat-1"])
})
