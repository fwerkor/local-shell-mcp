import { BaseController, type NativePageContext } from "./common"

type LoginTicket = { url: string; ticket: string }

/** The chat implementation lives in LibreChat; the WebUI owns only the LSM identity handoff. */
export class LibreChatController extends BaseController {
  private frame: HTMLIFrameElement | null = null
  private loading = false
  private chatOrigin = ""

  constructor(context: NativePageContext) { super(context) }

  mount(root: HTMLElement): void {
    this.root = root
    root.innerHTML = `<section class="lsm-librechat">
      <div class="lsm-librechat-loading" role="status" data-chat-status>
        Connecting to Chat…
      </div>
      <iframe class="lsm-librechat-frame" name="lsm-librechat-frame"
        title="LSM Chat" referrerpolicy="no-referrer"
        allow="clipboard-read; clipboard-write" hidden></iframe>
      <button type="button" data-chat-reconnect hidden>Reconnect Chat</button>
    </section>`
    this.frame = root.querySelector<HTMLIFrameElement>("iframe")!
    this.listen(root.querySelector<HTMLButtonElement>("[data-chat-reconnect]")!, "click", () => {
      void this.signIn()
    })
    const receive = (event: MessageEvent) => {
      if (event.source !== this.frame?.contentWindow || event.origin !== this.chatOrigin) return
      if (event.data?.type !== "lsm:upload" || !(event.data.file instanceof File)) return
      void this.upload(event.data.file)
    }
    window.addEventListener("message", receive)
    this.listeners.push(() => window.removeEventListener("message", receive))
    void this.signIn()
  }

  private async signIn(): Promise<void> {
    if (this.loading || this.destroyed) return
    this.loading = true
    const status = this.root.querySelector<HTMLElement>("[data-chat-status]")!
    const reconnect = this.root.querySelector<HTMLButtonElement>("[data-chat-reconnect]")!
    reconnect.hidden = true
    status.hidden = false
    status.textContent = "Connecting to Chat…"
    try {
      const { url, ticket } = await this.context.api.send<LoginTicket>("/librechat/ticket", "POST", {})
      if (this.destroyed || !this.frame) return
      const origin = new URL(url)
      if (origin.protocol !== "https:" && !(origin.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname))) {
        throw new Error("Chat requires a secure HTTPS origin")
      }
      const form = document.createElement("form")
      form.method = "POST"
      this.chatOrigin = origin.origin
      form.action = origin.origin + "/api/auth/lsm"
      form.target = this.frame.name
      form.hidden = true
      const input = document.createElement("input")
      input.type = "hidden"
      input.name = "ticket"
      input.value = ticket
      form.appendChild(input)
      this.root.appendChild(form)
      this.frame.hidden = false
      this.listen(this.frame, "load", () => {
        if (this.destroyed) return
        status.hidden = true
        // The upload button lives inside LibreChat's native composer.
      })
      form.submit()
      form.remove()
      input.value = ""
    } catch (error) {
      if (this.destroyed) return
      status.textContent = error instanceof Error ? error.message : String(error)
      reconnect.hidden = false
      this.context.notify(status.textContent, "error")
    } finally {
      this.loading = false
    }
  }

  private async upload(file: File): Promise<void> {
    if (file.size <= 0 || file.size > 32 * 1024 * 1024) {
      this.context.notify("Attachments must be between 1 byte and 32 MiB", "error")
      return
    }
    try {
      const headers: Record<string, string> = {}
      const token = this.context.accessToken()
      if (token) headers.Authorization = `Bearer ${token}`
      const response = await fetch(`${this.context.apiPrefix || "/api/ui"}/librechat/upload?name=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers,
        body: file,
      })
      const payload = await response.json() as {
        ok?: boolean; message?: string; error?: string; data?: { path: string; machine: string }
      }
      if (!response.ok || !payload.ok || !payload.data?.path) {
        throw new Error(payload.message || payload.error || "Local attachment upload failed")
      }
      this.frame?.contentWindow?.postMessage(
        { type: "lsm:local-attachment", path: payload.data.path },
        this.chatOrigin,
      )
      this.context.notify("File saved to LSM local machine; path added to the chat prompt.", "success")
    } catch (error) {
      this.context.notify(error instanceof Error ? error.message : String(error), "error")
    }
  }

  refresh(): void {}

  destroy(): void {
    this.frame = null
    super.destroy()
  }
}
