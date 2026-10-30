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

test("manual compact invokes endpoint and reloads same conversation without changing other selections", async () => {
  const controller: any = new HostedChatController({} as any)
  controller.active = { id: "chat-1", status: "idle", context: { summary: "", through: 0 } }
  controller.showArchives = false
  const events: string[] = []
  controller.renderConversation = () => { events.push(`render:${controller.busy}`) }
  controller.post = async (action: string, payload: { id: string }) => {
    events.push(`${action}:${payload.id}`)
    expect(action).toBe("conversation-compact")
    expect(payload.id).toBe("chat-1")
    return {}
  }
  controller.select = async (id: string) => { events.push(`select:${id}`) }
  await controller.action("compact")
  expect(events).toContain("conversation-compact:chat-1")
  expect(events).toContain("select:chat-1")
  expect(controller.busy).toBe(false)
  expect(events).toContain("render:true")
  controller.showArchives = true
  const before = events.length
  await controller.action("compact")
  expect(events.length).toBe(before)
})

test("late session attachment response cannot reselect an earlier chat", async () => {
  const controller: any = new HostedChatController({} as any)
  const previousWindow = (globalThis as any).window
  ;(globalThis as any).window = { prompt: () => "lsm-session-a" }
  try {
    controller.active = { id: "chat-a", session_id: "old", status: "idle" }
    let finish!: (record: any) => void
    controller.post = () => new Promise((resolve) => { finish = resolve })
    controller.renderConversation = () => undefined
    controller.closeWorkspace = async () => { throw new Error("late session response must not close workspace") }
    const pending = controller.action("session")
    controller.selectionEpoch++
    controller.active = { id: "chat-b", session_id: "session-b", status: "idle" }
    finish({ id: "chat-a", session_id: "lsm-session-a" })
    await pending
    expect(controller.active.id).toBe("chat-b")
    expect(controller.active.session_id).toBe("session-b")
  } finally { (globalThis as any).window = previousWindow }
})

test("conversation selection discards responses that arrive in reverse order", async () => {
  const controller: any = new HostedChatController({} as any)
  const replies = new Map<string, (value: any) => void>()
  const rendered: string[] = []
  controller.root = {} // Rendering methods are stubbed to test only selection ordering.
  controller.get = (_action: string, query: string) => new Promise((resolve) => {
    replies.set(new URLSearchParams(query.slice(1)).get("id")!, resolve)
  })
  controller.closeWorkspace = async () => undefined
  controller.renderConversation = () => { rendered.push(controller.active?.id || "none") }
  controller.renderList = () => undefined
  controller.startPolling = () => undefined
  const selectA = controller.select("chat-a")
  const selectB = controller.select("chat-b")
  replies.get("chat-b")!({ id: "chat-b", status: "idle" })
  await selectB
  replies.get("chat-a")!({ id: "chat-a", status: "idle" })
  await selectA
  expect(controller.active.id).toBe("chat-b")
  expect(rendered.at(-1)).toBe("chat-b")
})

test("conversation selection rechecks freshness after workspace teardown", async () => {
  const controller: any = new HostedChatController({} as any)
  controller.active = { id: "old", status: "idle" }
  let finishClose!: () => void
  let closes = 0
  controller.closeWorkspace = () => ++closes === 1
    ? new Promise<void>((resolve) => { finishClose = resolve }) : Promise.resolve()
  controller.get = async (_action: string, query: string) => ({ id: query.slice(4), status: "idle" })
  controller.renderConversation = () => undefined
  controller.renderList = () => undefined
  controller.startPolling = () => undefined
  const selectA = controller.select("chat-a")
  await Promise.resolve()
  const selectB = controller.select("chat-b")
  await Promise.resolve()
  finishClose()
  await selectB
  await selectA
  expect(controller.active.id).toBe("chat-b")
})

test("late reload cannot steal an in-flight manual conversation selection", async () => {
  const controller: any = new HostedChatController({} as any)
  let release!: (value: any) => void
  controller.get = async (action: string) => action === "profiles"
    ? new Promise((resolve) => { release = resolve })
    : action === "conversations" ? [{ id: "chat-a", title: "Old", status: "idle", profile_id: "p" }] : []
  controller.renderList = () => undefined
  controller.renderConversation = () => undefined
  const selected: string[] = []
  controller.select = async (id: string) => { selected.push(id) }
  const reload = controller.reload()
  ++controller.selectionEpoch  // The user selected another chat while reload was pending.
  release([])
  await reload
  expect(selected).toEqual([])
})
