import { BaseController, type NativePageContext } from "./common"

type LoginTicket = { url: string; ticket: string }

/** Exchange LSM authorization for a single-user workspace session. */
export function libreChatLoginAction(url: string): string {
  const destination = new URL(url)
  const local = destination.protocol === "http:" &&
    ["localhost", "127.0.0.1", "[::1]"].includes(destination.hostname)
  if ((destination.protocol !== "https:" && !local) ||
      destination.username || destination.password) {
    throw new Error("Workspace requires a secure HTTPS origin")
  }
  return destination.origin + "/api/auth/lsm"
}

/** The LSM WebUI is the login gateway; LibreChat renders the whole workspace. */
export class LibreChatController extends BaseController {
  private loading = false

  constructor(context: NativePageContext) { super(context) }

  mount(root: HTMLElement): void {
    this.root = root
    root.innerHTML = `<section class="lsm-librechat">
      <div class="lsm-librechat-loading" role="status" data-chat-status>
        Opening LSM Workspace…
      </div>
      <button type="button" data-chat-reconnect hidden>Retry</button>
    </section>`
    this.listen(root.querySelector<HTMLButtonElement>("[data-chat-reconnect]")!, "click", () => {
      void this.signIn()
    })
    void this.signIn()
  }

  private async signIn(): Promise<void> {
    if (this.loading || this.destroyed) return
    this.loading = true
    const status = this.root.querySelector<HTMLElement>("[data-chat-status]")!
    const reconnect = this.root.querySelector<HTMLButtonElement>("[data-chat-reconnect]")!
    reconnect.hidden = true
    status.textContent = "Opening LSM Workspace…"
    try {
      const { url, ticket } = await this.context.api.send<LoginTicket>("/librechat/ticket", "POST", {})
      if (this.destroyed) return
      const action = libreChatLoginAction(url)
      const form = document.createElement("form")
      form.method = "POST"
      form.action = action
      form.target = "_top"
      form.hidden = true
      const input = document.createElement("input")
      input.type = "hidden"
      input.name = "ticket"
      input.value = ticket
      form.appendChild(input)
      this.root.appendChild(form)
      form.submit()
      input.value = ""
      form.remove()
    } catch (error) {
      if (this.destroyed) return
      status.textContent = error instanceof Error ? error.message : String(error)
      reconnect.hidden = false
      this.context.notify(status.textContent, "error")
    } finally {
      this.loading = false
    }
  }

  refresh(): void {}
}
