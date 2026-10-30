import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge"
import { BaseController, escapeHtml, type NativePageContext } from "./common"

type Profile = { id: string; name: string; model: string; endpoint: string; has_key: boolean; context_window?: number }
type Message = { role: "user" | "assistant" | "tool"; content?: string | null; tool_calls?: unknown[] }
type Conversation = {
  id: string; title: string; profile_id: string; session_id?: string | null;
  status: string; archived_at?: number; error?: string | null; context?: { summary: string; through: number }; messages: Message[]; events: { type: string; name?: string; error?: boolean; call_id?: string; result?: { content?: { type?: string; text?: string }[] } }[]
}
type Summary = Pick<Conversation, "id" | "title" | "profile_id" | "session_id" | "status" | "archived_at">

export class HostedChatController extends BaseController {
  private profiles: Profile[] = []
  private conversations: Summary[] = []
  private archives: Summary[] = []
  private showArchives = false
  private selectionEpoch = 0
  private archiveFilter = ""
  private active: Conversation | null = null
  private bridge: AppBridge | null = null
  private frame: HTMLIFrameElement | null = null
  private workspaceEpoch = 0
  private modelContext = ""
  private polling = false
  private busy = false

  constructor(context: NativePageContext) { super(context) }

  mount(root: HTMLElement): void {
    this.root = root
    root.innerHTML = `<div class="hosted-chat">
      <aside class="hosted-chats">
        <div class="hosted-chats-head"><strong data-chat-heading>Conversations</strong><button type="button" data-chat-action="new">+ New</button></div>
        <input data-chat-archive-filter class="hosted-archive-filter" placeholder="Find archived conversations" aria-label="Filter archived conversations by title" hidden />
        <div data-chat-list class="hosted-chats-list"></div>
        <button type="button" data-chat-action="archives" class="hosted-settings">Archived conversations</button>
        <button type="button" data-chat-action="profile" class="hosted-settings">Model profiles</button>
      </aside>
      <section class="hosted-main">
        <div class="hosted-toolbar">
          <div class="hosted-model"><select data-chat-model aria-label="Model profile"></select><span data-chat-status></span></div>
          <div class="hosted-toolbar-actions">
            <button type="button" data-chat-action="session">Attach LSM Session</button>
            <button type="button" data-chat-action="workspace">Live Workspace</button>
            <button type="button" data-chat-action="compact">Compact</button>
            <button type="button" data-chat-action="archive">Archive</button>
            <button type="button" data-chat-action="restore" hidden>Restore</button>
            <button type="button" data-chat-action="delete">Delete</button>
          </div>
        </div>
        <div class="hosted-context-info" data-chat-context-info hidden></div>
        <div class="hosted-messages" data-chat-messages aria-live="polite"></div>
        <form class="hosted-composer" data-chat-form>
          <textarea data-chat-input rows="3" placeholder="Ask anything or use LSM tools…"></textarea>
          <div class="hosted-composer-bottom"><span>Model runs on your configured endpoint. Conversations are stored on this server.</span>
          <button type="button" data-chat-action="stop" hidden>Stop</button><button type="submit" data-chat-send>Send</button></div>
        </form>
      </section>
      <aside class="hosted-workspace" data-chat-workspace hidden>
        <header><strong>LSM Live Workspace</strong><button type="button" data-chat-action="close-workspace">Close</button></header>
        <div data-chat-app></div>
      </aside>
      <dialog class="hosted-profile-dialog" data-chat-profile-dialog>
        <form data-chat-profile-form>
          <h3>Model profiles</h3>
          <label>Manage existing profile
            <select data-profile-existing><option value="">Create new profile</option></select>
          </label>
          <label>Profile name <input name="name" required maxlength="120" placeholder="My model"></label>
          <label>API endpoint <input name="endpoint" type="url" required placeholder="https://api.example.com/v1"></label>
          <label>Model ID <input name="model" required placeholder="model-name"></label>
          <label>Context window (tokens) <input name="context_window" type="number" required min="8192" max="1000000" step="1" value="32768"></label>
          <p>Context usage is conservatively estimated. Auto-compact starts near 80% of this window and preserves the full original history.</p>
          <label>API Key <input name="api_key" type="password" autocomplete="off" placeholder="Enter key or leave blank to retain"></label>
          <p>API keys are encrypted in server state; they are never returned to this browser.</p>
          <div class="hosted-dialog-actions">
            <button type="button" data-chat-action="profile-delete">Delete profile</button>
            <button type="button" data-chat-action="profile-close">Cancel</button>
            <button type="submit">Save profile</button>
          </div>
        </form>
      </dialog>
    </div>`
    this.listen(root, "click", (event) => {
      const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-chat-action]")
      if (!button) return
      void this.action(button.dataset.chatAction || "", button.dataset.id)
    })
    this.listen(root.querySelector<HTMLFormElement>("[data-chat-form]")!, "submit", (event) => {
      event.preventDefault()
      void this.send()
    })
    this.listen(root.querySelector<HTMLTextAreaElement>("[data-chat-input]")!, "keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault()
        void this.send()
      }
    })
    this.listen(root.querySelector<HTMLInputElement>("[data-chat-archive-filter]")!, "input", (event) => {
      this.archiveFilter = (event.target as HTMLInputElement).value
      this.renderList()
    })
    this.listen(root.querySelector<HTMLSelectElement>("[data-chat-model]")!, "change", (event) => {
      void this.changeModel((event.target as HTMLSelectElement).value)
    })
    this.listen(root.querySelector<HTMLFormElement>("[data-chat-profile-form]")!, "submit", (event) => {
      event.preventDefault()
      void this.saveProfile()
    })
    this.listen(root.querySelector<HTMLSelectElement>("[data-profile-existing]")!, "change", () => this.populateProfileForm())
    this.root.querySelector<HTMLButtonElement>('[data-chat-action="workspace"]')!.hidden = this.context.liveWorkspaceEnabled !== true
    void this.reload()
  }

  private async get<T>(action: string, query = ""): Promise<T> {
    return this.context.api.get<T>(`/hosted-chat/${action}${query}`)
  }

  private async post<T>(action: string, body: Record<string, unknown>): Promise<T> {
    return this.context.api.send<T>(`/hosted-chat/${action}`, "POST", body)
  }

  private async reload(): Promise<void> {
    try {
      const viewArchives = this.showArchives
      const selectionEpoch = this.selectionEpoch
      const [profiles, conversations, archives] = await Promise.all([
        this.get<Profile[]>("profiles"), this.get<Summary[]>("conversations"),
        viewArchives ? this.get<Summary[]>("archives") : Promise.resolve([]),
      ])
      if (this.destroyed || this.showArchives !== viewArchives) return
      this.profiles = profiles
      this.conversations = conversations
      if (viewArchives) this.archives = archives
      this.renderList()
      const available = viewArchives ? archives : conversations
      if (!this.active && available.length && this.selectionEpoch === selectionEpoch) await this.select(available[0].id)
      else this.renderConversation()
    } catch (error) { this.notifyError(error) }
  }

  private notifyError(error: unknown): void {
    this.context.notify(error instanceof Error ? error.message : String(error), "error")
  }

  private renderList(): void {
    const list = this.root.querySelector<HTMLElement>("[data-chat-list]")!
    const source = this.showArchives ? this.archives : this.conversations
    const visible = this.showArchives && this.archiveFilter.trim()
      ? source.filter((item) => item.title.toLocaleLowerCase().includes(this.archiveFilter.trim().toLocaleLowerCase()))
      : source
    list.innerHTML = visible.length ? visible.map((conversation) =>
      `<button type="button" data-chat-action="select" data-id="${escapeHtml(conversation.id)}"
       class="${conversation.id === this.active?.id ? "active" : ""}">
       <span>${escapeHtml(conversation.title || "New chat")}</span><small>${conversation.status === "running" ? "Running" : ""}</small></button>`
    ).join("") : `<p class="hosted-empty">${this.showArchives ? "No matching archived conversations." : "No conversations yet."}</p>`
    this.root.querySelector<HTMLElement>("[data-chat-heading]")!.textContent = this.showArchives ? "Archived" : "Conversations"
    this.root.querySelector<HTMLButtonElement>('[data-chat-action="new"]')!.hidden = this.showArchives
    this.root.querySelector<HTMLButtonElement>('[data-chat-action="archives"]')!.textContent = this.showArchives ? "Back to conversations" : "Archived conversations"
    this.root.querySelector<HTMLInputElement>("[data-chat-archive-filter]")!.hidden = !this.showArchives
    const select = this.root.querySelector<HTMLSelectElement>("[data-chat-model]")!
    const selected = this.active?.profile_id || select.value
    select.innerHTML = this.profiles.map((p) =>
      `<option value="${escapeHtml(p.id)}"${selected === p.id ? " selected" : ""}>${escapeHtml(p.name)} · ${escapeHtml(p.model)}</option>`
    ).join("")
  }

  private renderConversation(): void {
    if (this.destroyed) return
    const messages = this.root.querySelector<HTMLElement>("[data-chat-messages]")!
    const active = this.active
    if (!active) {
      messages.innerHTML = this.showArchives
        ? '<div class="hosted-welcome"><h2>Archived conversations</h2><p>Select a conversation to read it, or restore it to continue.</p></div>'
        : '<div class="hosted-welcome"><h2>Hosted Chat</h2><p>Configure your model profile, then start a conversation. LSM tools are available through MCP.</p></div>'
    } else {
      const visible = active.messages.filter((m) => m.role !== "tool" && (!m.tool_calls?.length || m.content))
      const activity = active.events.map((event) => {
        const output = (event.result?.content || []).filter((item) => item.type === "text")
          .map((item) => item.text || "").join("\n").slice(0, 2000)
        return `<details class="hosted-tool-event"><summary>${event.error ? "Failed" : "Tool"}: ${escapeHtml(event.name || "unknown")}</summary>` +
          `<pre>${escapeHtml(output || (event.error ? "Tool failed" : "No text output"))}</pre></details>`
      }).join("")
      messages.innerHTML = visible.map((m) =>
        `<article class="hosted-message ${m.role}"><div class="hosted-message-label">${m.role === "user" ? "You" : "Assistant"}</div><div class="hosted-message-body">${escapeHtml(m.content || "").replaceAll("\n", "<br>")}</div></article>`
      ).join("") + (activity ? `<section class="hosted-tool-activity" aria-label="Tool activity"><strong>Tool activity (${active.events.length})</strong>${activity}</section>` : "") +
        (this.showArchives ? '<p class="hosted-running">Archived · restore this conversation to continue.</p>' : active.status === "running" ? '<div class="hosted-running">Agent running · waiting for model or tools…</div>' : "") +
        (active.error ? `<p class="hosted-error">${escapeHtml(active.error)}</p>` : "")
    }
    const contextInfo = this.root.querySelector<HTMLElement>("[data-chat-context-info]")!
    contextInfo.hidden = !active || this.showArchives
    if (active && !this.showArchives) {
      const through = active.context?.through || 0
      contextInfo.innerHTML = through
        ? `<details><summary>Context compacted · ${through} older messages summarized</summary><pre>${escapeHtml(active.context?.summary || "")}</pre></details>`
        : '<span>Context: full recent transcript · automatic compact enabled</span>'
    }
    const status = this.root.querySelector<HTMLElement>("[data-chat-status]")!
    status.textContent = active?.session_id ? `LSM: ${active.session_id}` : active?.status || "No session attached"
    const stop = this.root.querySelector<HTMLButtonElement>('[data-chat-action="stop"]')!
    stop.hidden = this.showArchives || active?.status !== "running"
    const compact = this.root.querySelector<HTMLButtonElement>('[data-chat-action="compact"]')!
    compact.hidden = this.showArchives || !active
    compact.disabled = this.busy || active?.status === "running"
    compact.textContent = this.busy ? "Working…" : "Compact"
    this.root.querySelector<HTMLButtonElement>('[data-chat-action="archive"]')!.hidden = this.showArchives || !active
    this.root.querySelector<HTMLButtonElement>('[data-chat-action="archive"]')!.disabled = active?.status === "running"
    this.root.querySelector<HTMLButtonElement>('[data-chat-action="restore"]')!.hidden = !this.showArchives || !active
    this.root.querySelector<HTMLButtonElement>('[data-chat-action="session"]')!.hidden = this.showArchives
    this.root.querySelector<HTMLButtonElement>('[data-chat-action="workspace"]')!.hidden = this.showArchives || this.context.liveWorkspaceEnabled !== true
    this.root.querySelector<HTMLButtonElement>("[data-chat-send]")!.disabled = this.showArchives || !active || active.status === "running" || this.busy
    this.root.querySelector<HTMLTextAreaElement>("[data-chat-input]")!.disabled = this.showArchives
    const selector = this.root.querySelector<HTMLSelectElement>("[data-chat-model]")!
    selector.disabled = this.showArchives || active?.status === "running"
    if (active) selector.value = active.profile_id
  }

  private async select(id: string): Promise<void> {
    const epoch = ++this.selectionEpoch
    const viewArchives = this.showArchives
    try {
      const switching = this.active?.id !== id
      if (switching) { this.active = null; this.renderConversation() }
      const data = await this.get<Conversation>(viewArchives ? "archive" : "conversation", `?id=${encodeURIComponent(id)}`)
      if (this.destroyed || this.showArchives !== viewArchives || this.selectionEpoch !== epoch) return
      if (switching) {
        this.modelContext = ""
        await this.closeWorkspace()
        if (this.destroyed || this.showArchives !== viewArchives || this.selectionEpoch !== epoch) return
      }
      this.active = data
      this.renderList()
      this.renderConversation()
      this.startPolling()
    } catch (error) { this.notifyError(error) }
  }

  private startPolling(): void {
    if (this.polling || this.destroyed || this.active?.status !== "running") return
    this.polling = true
    const tick = async () => {
      let failures = 0
      try {
        while (!this.destroyed && this.active?.status === "running") {
          await new Promise((resolve) => setTimeout(resolve, failures ? Math.min(15000, 1200 * 2 ** failures) : 1200))
          if (!this.active || this.destroyed) break
          const id = this.active.id
          try {
            const record = await this.get<Conversation>("conversation", `?id=${encodeURIComponent(id)}`)
            if (!this.active || this.active.id !== id || this.destroyed) break
            this.active = record
            failures = 0
            this.renderConversation()
            if (record.status !== "running") await this.reload()
          } catch (error) {
            failures++
            if (failures === 1) this.notifyError(error)
          }
        }
      } finally {
        this.polling = false
        if (!this.destroyed && this.active?.status === "running") this.startPolling()
      }
    }
    void tick()
  }

  private async send(text?: string): Promise<boolean> {
    if (this.busy || this.showArchives || !this.active || this.active.status === "running") return false
    const input = this.root.querySelector<HTMLTextAreaElement>("[data-chat-input]")!
    const content = text ?? input.value
    if (!content.trim()) return false
    this.busy = true
    this.renderConversation()
    try {
      const id = this.active.id
      const message = this.modelContext ? `${this.modelContext}\n\n${content}` : content
      await this.post("send", { id, text: message })
      if (this.active?.id === id) {
        this.modelContext = ""
        input.value = ""
        await this.select(id)
      }
      return true
    } catch (error) {
      this.notifyError(error)
      return false
    } finally { this.busy = false; this.renderConversation() }
  }

  private async action(action: string, id?: string): Promise<void> {
    try {
      if (action === "select" && id) { await this.select(id); return }
      if (action === "archives") {
        ++this.selectionEpoch
        await this.closeWorkspace()
        this.showArchives = !this.showArchives
        this.active = null
        await this.reload()
        return
      }
      if (action === "profile") { this.profileDialog(); return }
      if (action === "profile-close") { this.root.querySelector<HTMLDialogElement>("[data-chat-profile-dialog]")?.close(); return }
      if (action === "profile-delete") { await this.deleteProfile(); return }
      if (action === "new" && !this.showArchives) {
        ++this.selectionEpoch
        this.modelContext = ""
        if (!this.profiles.length) { this.profileDialog(); return }
        const profileId = this.active?.profile_id || this.profiles[0].id
        const conversation = await this.post<Conversation>("conversation-create", { profile_id: profileId })
        this.active = null
        await this.reload()
        await this.select(conversation.id)
        return
      }
      if (!this.active) return
      if (action === "delete") {
        if (!window.confirm("Permanently delete this conversation and its history?")) return
        await this.post(this.showArchives ? "archive-delete" : "conversation-delete", { id: this.active.id })
        await this.closeWorkspace()
        this.active = null
        await this.reload()
      } else if (action === "compact" && !this.showArchives && !this.busy && this.active.status !== "running") {
        const cid = this.active.id
        this.busy = true
        this.renderConversation()
        try {
          await this.post("conversation-compact", { id: cid })
          if (this.active?.id === cid && !this.showArchives) await this.select(cid)
        } finally { this.busy = false; this.renderConversation() }
      } else if (action === "archive" && !this.showArchives) {
        const cid = this.active.id
        await this.post("conversation-archive", { id: cid })
        await this.closeWorkspace()
        this.active = null
        await this.reload()
      } else if (action === "restore" && this.showArchives) {
        const cid = this.active.id
        await this.post("conversation-restore", { id: cid })
        this.showArchives = false
        this.active = null
        await this.reload()
        await this.select(cid)
      } else if (action === "stop" && !this.showArchives) {
        await this.post("stop", { id: this.active.id })
      } else if (action === "session" && !this.showArchives) {
        const id = this.active.id
        const epoch = this.selectionEpoch
        const response = window.prompt("LSM Logical Session ID (leave empty to detach)", this.active.session_id || "")
        if (response === null) return
        const previousSessionId = this.active.session_id || null
        const updated = await this.post<Conversation>("conversation-update", {
          id, session_id: response.trim(),
        })
        if (this.destroyed || this.showArchives || this.selectionEpoch !== epoch || this.active?.id !== id) return
        this.active = updated
        if ((updated.session_id || null) !== previousSessionId) {
          const reopen = !!this.bridge || !!this.frame
          await this.closeWorkspace()
          if (this.destroyed || this.showArchives || this.selectionEpoch !== epoch || this.active?.id !== id) return
          if (reopen) await this.openWorkspace()
        }
        this.renderConversation()
      } else if (action === "workspace") {
        await this.openWorkspace()
      } else if (action === "close-workspace") {
        await this.closeWorkspace()
      }
    } catch (error) { this.notifyError(error) }
  }

  private async changeModel(profileId: string): Promise<void> {
    if (!this.active || this.showArchives || this.active.status === "running") return
    try {
      const id = this.active.id
      const updated = await this.post<Conversation>("conversation-update", { id, profile_id: profileId })
      if (this.destroyed || this.showArchives || this.active?.id !== id) return
      this.active = updated
      this.renderConversation()
    } catch (error) { this.notifyError(error) }
  }

  private profileDialog(): void {
    const dialog = this.root.querySelector<HTMLDialogElement>("[data-chat-profile-dialog]")!
    const select = dialog.querySelector<HTMLSelectElement>("[data-profile-existing]")!
    select.innerHTML = '<option value="">Create new profile</option>' +
      this.profiles.map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join("")
    this.populateProfileForm()
    dialog.showModal()
  }

  private populateProfileForm(): void {
    const dialog = this.root.querySelector<HTMLDialogElement>("[data-chat-profile-dialog]")!
    const form = dialog.querySelector<HTMLFormElement>("form")!
    const id = dialog.querySelector<HTMLSelectElement>("[data-profile-existing]")!.value
    const profile = this.profiles.find((p) => p.id === id)
    for (const name of ["name", "model", "endpoint"] as const) {
      (form.elements.namedItem(name) as HTMLInputElement).value = profile?.[name] || ""
    }
    (form.elements.namedItem("context_window") as HTMLInputElement).value = `${profile?.context_window ?? 32768}`;
    (form.elements.namedItem("api_key") as HTMLInputElement).value = "";
    (form.elements.namedItem("api_key") as HTMLInputElement).required = false;
    dialog.querySelector<HTMLButtonElement>('[data-chat-action="profile-delete"]')!.disabled = !profile
  }

  private async saveProfile(): Promise<void> {
    const dialog = this.root.querySelector<HTMLDialogElement>("[data-chat-profile-dialog]")!
    const form = dialog.querySelector<HTMLFormElement>("form")!
    const id = dialog.querySelector<HTMLSelectElement>("[data-profile-existing]")!.value
    const payload: Record<string, string> = {}
    for (const name of ["name", "model", "endpoint", "api_key"]) {
      payload[name] = (form.elements.namedItem(name) as HTMLInputElement).value.trim()
    }
    try {
      const windowSize = Number((form.elements.namedItem("context_window") as HTMLInputElement).value)
      await this.post("profile-save", { ...payload, context_window: windowSize, ...(id ? { id } : {}) })
      dialog.close()
      await this.reload()
    } catch (error) { this.notifyError(error) }
  }

  private async deleteProfile(): Promise<void> {
    const dialog = this.root.querySelector<HTMLDialogElement>("[data-chat-profile-dialog]")!
    const id = dialog.querySelector<HTMLSelectElement>("[data-profile-existing]")!.value
    if (!id || !window.confirm("Delete this model profile? Existing chats will need another profile.")) return
    await this.post("profile-delete", { id })
    dialog.close()
    await this.reload()
  }

  private async openWorkspace(): Promise<void> {
    if (!this.active || this.bridge) return
    if (this.context.liveWorkspaceEnabled !== true) throw new Error("Live Workspace is disabled")
    const conversationId = this.active.id
    const epoch = this.workspaceEpoch
    const args = { session_id: this.active.session_id || null }
    const result = await this.post<Record<string, unknown>>("tool", { name: "workspace_open", arguments: args })
    if (result.isError) throw new Error("Unable to open LSM Live Workspace")
    const uri = "ui://local-shell-mcp/live-workspace.html"
    const resource = await this.post<{ contents: { text?: string }[] }>("resource", { uri })
    const html = resource.contents?.[0]?.text
    if (!html) throw new Error("No workspace UI resource was returned")
    if (this.destroyed || epoch !== this.workspaceEpoch || this.active?.id !== conversationId) return
    const holder = this.root.querySelector<HTMLElement>("[data-chat-workspace]")!
    const target = this.root.querySelector<HTMLElement>("[data-chat-app]")!
    holder.hidden = false
    const frame = document.createElement("iframe")
    frame.title = "LSM Live Workspace"
    frame.className = "hosted-app-frame"
    frame.setAttribute("sandbox", "allow-scripts allow-forms")
    target.replaceChildren(frame)
    this.frame = frame
    if (!frame.contentWindow || this.destroyed) return
    const bridge = new AppBridge(null, { name: "lsm-hosted-chat", version: "0.1.0" },
      { serverTools: {} },
      { hostContext: { theme: "light", displayMode: "inline", availableDisplayModes: ["inline", "fullscreen"] } })
    this.bridge = bridge
    bridge.oncalltool = async (params) => {
      if (params.name !== "live_workspace_reconnect") throw new Error("App tool not permitted")
      return await this.post("tool", { name: params.name, arguments: params.arguments || {} }) as never
    }
    bridge.onmessage = async (params) => {
      const text = params.content.filter((block) => block.type === "text").map((block) =>
        block.type === "text" ? block.text : "").join("\n\n")
      if (!await this.send(text)) throw new Error("Hosted Chat message was not accepted; retry after the current turn finishes")
      return {}
    }
    bridge.onupdatemodelcontext = async (params) => {
      if (this.bridge !== bridge) return {}
      this.modelContext = (params.content || []).filter((part) => part.type === "text")
        .map((part) => part.type === "text" ? part.text : "").join("\n\n")
      return {}
    }
    bridge.onrequestdisplaymode = async ({ mode }) => {
      holder.classList.toggle("expanded", mode === "fullscreen")
      bridge.setHostContext({ displayMode: mode === "fullscreen" ? "fullscreen" : "inline" })
      return { mode: mode === "fullscreen" ? "fullscreen" : "inline" }
    }
    bridge.oninitialized = () => {
      void (async () => {
        await bridge.sendToolInput({ arguments: args })
        await bridge.sendToolResult(result as never)
      })()
    }
    await bridge.connect(new PostMessageTransport(frame.contentWindow, frame.contentWindow))
    if (!this.destroyed && this.bridge === bridge && epoch === this.workspaceEpoch && this.active?.id === conversationId) frame.srcdoc = html
  }

  private async closeWorkspace(): Promise<void> {
    this.workspaceEpoch++
    this.modelContext = ""
    await this.bridge?.close().catch(() => undefined)
    this.bridge = null
    this.frame?.remove()
    this.frame = null
    if (!this.destroyed) {
      const holder = this.root.querySelector<HTMLElement>("[data-chat-workspace]")
      if (holder) { holder.hidden = true; holder.classList.remove("expanded") }
    }
  }

  refresh(): void {
    this.startPolling()
  }

  override destroy(): void {
    super.destroy()
    void this.closeWorkspace()
  }
}
