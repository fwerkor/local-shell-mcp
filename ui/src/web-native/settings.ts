import { BaseController, confirmDialog, escapeHtml, type NativePageContext } from "./common"

type Field = { name: string; group: string; type: "boolean" | "integer" | "list" | "text"; value: unknown; configured: boolean; sensitive: boolean; locked: boolean; pending: boolean; source: "environment" | "config" | "default"; choices: string[] | null }
type Snapshot = { path: string; revision: string; fields: Field[]; running: { port: number; ui_path: string } }
const CRITICAL = new Set(["host", "port", "mode", "auth_mode", "ui_enabled", "ui_path", "state_dir", "state_backend", "stateless_controller", "oauth_jwt_secret", "public_base_url"])
const HELP: Record<string, string> = {
  host: "Controller listen address", port: "Listener port (may change the browser URL)",
  ui_path: "WebUI URL prefix", auth_mode: "Disabling authentication can expose the controller",
  oauth_jwt_secret: "Changing this invalidates current OAuth tokens", oauth_admin_pin: "PIN used to approve OAuth clients",
  hosted_chat_enabled: "Enable hosted BYOK Chat", workspace_root: "Local filesystem workspace root",
  state_dir: "Directory for controller state", allow_full_container: "Disable built-in command and path restrictions",
}

export function restartDestination(currentUrl: string, runningPort: number, nextPort: number, nextPath: string): string {
  const url = new URL(currentUrl)
  // Only change the port for direct connections. A reverse proxy's external port
  // is independently configured and must not be rewritten.
  const effectivePort = url.port ? Number(url.port) : url.protocol === "https:" ? 443 : url.protocol === "http:" ? 80 : null
  if (effectivePort === runningPort && nextPort !== runningPort) {
    url.port = String(nextPort)
  }
  if (nextPath) url.pathname = `${nextPath.replace(/\/$/, "")}/`
  return url.href
}

export function nextRestartSettings(snapshot: Snapshot | null): { port: number; uiPath: string } {
  const running = snapshot?.running
  return {
    port: Number(snapshot?.fields.find(f => f.name === "port")?.value ?? running?.port ?? 0),
    uiPath: String(snapshot?.fields.find(f => f.name === "ui_path")?.value ?? running?.ui_path ?? ""),
  }
}

function fieldControl(field: Field): string {
  const name = escapeHtml(field.name)
  const disabled = field.locked ? " disabled" : ""
  const value = field.value
  if (field.type === "boolean") return `<select data-field="${name}"${disabled}><option value="true"${value === true ? " selected" : ""}>Enabled</option><option value="false"${value === false ? " selected" : ""}>Disabled</option></select>`
  if (field.choices) return `<select data-field="${name}"${disabled}>${field.choices.map(choice => `<option value="${escapeHtml(choice)}"${value === choice ? " selected" : ""}>${escapeHtml(choice)}</option>`).join("")}</select>`
  if (field.type === "list") return `<textarea data-field="${name}" rows="2"${disabled}>${escapeHtml(Array.isArray(value) ? value.join("\n") : "")}</textarea>`
  const type = field.sensitive ? "password" : field.type === "integer" ? "number" : "text"
  const shown = field.sensitive ? "" : String(value ?? "")
  return `<input data-field="${name}" type="${type}" value="${escapeHtml(shown)}"${disabled} autocomplete="off" placeholder="${field.sensitive && field.configured ? "Configured (enter to replace)" : ""}" />`
}

function fieldRow(field: Field, dirty: boolean): string {
  const name = escapeHtml(field.name)
  return `<div class="settings-field${dirty ? " pending" : ""}${field.locked ? " locked" : ""}" data-setting="${name}">
    <div class="settings-field-info"><label>${escapeHtml(field.name.replaceAll("_", " "))}<code>${name}</code></label>
      <span>${escapeHtml(HELP[field.name] || "")}</span><small>${field.locked ? "Environment override · read-only" : field.source === "config" ? "YAML override" : "Default"}${field.sensitive ? " · secret" : ""}${field.pending ? " · saved, restart pending" : ""}</small></div>
    <div class="settings-field-input">${fieldControl(field)}${field.locked ? "" : `<button type="button" data-reset="${name}" class="native-button"${field.source !== "config" && !dirty ? " disabled" : ""}>Reset</button>`}</div></div>`
}

export class SettingsController extends BaseController {
  private data: Snapshot | null = null
  private draft = new Map<string, unknown>()
  private filter = ""
  private group = "All"
  private busy = false
  private pendingRestart = false

  constructor(context: NativePageContext) { super(context) }

  mount(root: HTMLElement): void {
    this.root = root
    root.innerHTML = `<div class="native-loading">Loading settings…</div>`
    this.listen(root, "input", event => this.onInput(event))
    this.listen(root, "change", event => this.onInput(event))
    this.listen(root, "click", event => { void this.onClick(event) })
    void this.load()
  }

  refresh(): void { /* Preserve unsaved changes across dashboard polling. */ }

  private async load(): Promise<void> {
    if (this.busy) return
    this.busy = true
    try {
      const data = await this.context.api.get<Snapshot>("/settings/view")
      if (this.destroyed) return
      this.data = data
      this.pendingRestart = data.fields.some(field => field.pending)
      this.draft.clear()
      this.render()
    } catch (error) {
      if (!this.destroyed) {
        const message = error instanceof Error ? error.message : String(error)
        const reauthorize = message.includes("admin:config") && this.context.reauthorize
        this.root.innerHTML = `<div class="native-error"><p>${escapeHtml(message)}</p>${reauthorize ? '<button class="native-button primary" data-action="reauthorize">Reauthorize Settings access</button>' : ""}</div>`
      }
    } finally { this.busy = false }
  }

  private render(): void {
    if (!this.data || this.destroyed) return
    const groups = ["All", ...new Set(this.data.fields.map(f => f.group))]
    const grouped = new Map<string, Field[]>()
    for (const f of this.data.fields) grouped.set(f.group, [...(grouped.get(f.group) || []), f])
    this.root.innerHTML = `<section class="native-page settings-page"><header class="settings-heading"><div><h2>Controller settings</h2><p>Stored in <code>${escapeHtml(this.data.path)}</code>. Environment variables have priority.</p></div>
      <div class="settings-actions"><button class="native-button" data-action="reload"${this.draft.size ? " disabled" : ""}>Reload</button>
      <button class="native-button" data-action="save"${!this.draft.size ? " disabled" : ""}>Save (${this.draft.size})</button>
      <button class="native-button primary" data-action="apply"${!this.draft.size ? " disabled" : ""}>Save &amp; restart</button>
      <button class="native-button${this.pendingRestart ? " danger" : ""}" data-action="restart">Restart controller</button></div></header>
      <p class="settings-notice" role="status">${this.pendingRestart ? "Saved changes require a restart to take effect." : this.draft.size ? `${this.draft.size} unsaved edits. Save before restarting.` : "Changes take effect after restarting the controller."}</p>
      <div class="settings-filters"><input data-search type="search" placeholder="Search settings…" value="${escapeHtml(this.filter)}" aria-label="Search settings" />
      <select data-group aria-label="Setting group">${groups.map(g => `<option value="${escapeHtml(g)}"${g === this.group ? " selected" : ""}>${escapeHtml(g)}</option>`).join("")}</select><span data-setting-count>${this.data.fields.length} / ${this.data.fields.length}</span></div>
      ${[...grouped].map(([group, fields]) => `<section class="native-panel settings-group" data-settings-group="${escapeHtml(group)}"><header><h3>${escapeHtml(group)}</h3><span>${fields.length}</span></header><div>${fields.map(f => fieldRow(f, this.draft.has(f.name))).join("")}</div></section>`).join("") || '<div class="native-empty">No matching settings</div>'}</section>`
    this.filterRows()
    this.root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("[data-field]").forEach(control => {
      const name = control.dataset.field!
      if (!this.draft.has(name)) return
      const value = this.draft.get(name)
      if (value !== null) control.value = Array.isArray(value) ? value.join("\n") : String(value)
    })
  }

  private filterRows(): void {
    let shown = 0
    this.root.querySelectorAll<HTMLElement>("[data-settings-group]").forEach(section => {
      let groupVisible = 0
      section.querySelectorAll<HTMLElement>("[data-setting]").forEach(row => {
        const name = row.dataset.setting || ""
        const visible = (this.group === "All" || section.dataset.settingsGroup === this.group)
          && `${name} ${HELP[name] || ""}`.toLowerCase().includes(this.filter.toLowerCase())
        row.hidden = !visible
        if (visible) { groupVisible++; shown++ }
      })
      section.hidden = groupVisible === 0
      const count = section.querySelector<HTMLElement>("header > span")
      if (count) count.textContent = String(groupVisible)
    })
    const count = this.root.querySelector<HTMLElement>("[data-setting-count]")
    if (count) count.textContent = `${shown} / ${this.data?.fields.length || 0}`
  }

  private onInput(event: Event): void {
    const el = event.target
    if (!(el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement)) return
    if (el.hasAttribute("data-search")) { this.filter = el.value; this.filterRows(); return }
    if (el.hasAttribute("data-group")) { this.group = el.value; this.filterRows(); return }
    const field = this.data?.fields.find(f => f.name === el.dataset.field)
    if (!field || field.locked) return
    let value: unknown = el.value
    if (field.type === "boolean") value = el.value === "true"
    else if (field.type === "integer") {
      if (!/^-?\d+$/.test(el.value.trim())) return
      value = Number(el.value)
    } else if (field.type === "list") value = el.value.split(/[\n,]/).map(v => v.trim()).filter(Boolean)
    if (field.sensitive && !el.value || JSON.stringify(value) === JSON.stringify(field.value)) this.draft.delete(field.name)
    else this.draft.set(field.name, value)
    this.updatePending()
  }

  private updatePending(): void {
    const save = this.root.querySelector<HTMLButtonElement>('[data-action="save"]')
    if (save) { save.disabled = !this.draft.size; save.textContent = `Save (${this.draft.size})` }
    const apply = this.root.querySelector<HTMLButtonElement>('[data-action="apply"]')
    if (apply) apply.disabled = !this.draft.size
    const reload = this.root.querySelector<HTMLButtonElement>('[data-action="reload"]')
    if (reload) reload.disabled = this.draft.size > 0
    this.root.querySelectorAll<HTMLElement>("[data-setting]").forEach(row => {
      const name = row.dataset.setting!
      row.classList.toggle("pending", this.draft.has(name))
      const reset = row.querySelector<HTMLButtonElement>("[data-reset]")
      if (reset) reset.disabled = this.data?.fields.find(f => f.name === name)?.source !== "config" && !this.draft.has(name)
    })
    const notice = this.root.querySelector<HTMLElement>(".settings-notice")
    if (notice && this.draft.size) notice.textContent = `${this.draft.size} unsaved edits. Save before restarting.`
  }

  private async onClick(event: Event): Promise<void> {
    const el = event.target
    if (!(el instanceof Element) || this.busy) return
    const reset = el.closest<HTMLButtonElement>("[data-reset]")
    if (reset) { this.draft.set(reset.dataset.reset!, null); this.render(); return }
    const action = el.closest<HTMLElement>("[data-action]")?.dataset.action
    if (action === "reauthorize") { await this.context.reauthorize?.(); return }
    if (action === "reload") await this.load()
    if (action === "save") await this.save()
    if (action === "apply" && await this.save()) await this.restart()
    if (action === "restart") await this.restart()
  }

  private async save(): Promise<boolean> {
    if (!this.data || !this.draft.size) return false
    const changes = Object.fromEntries(this.draft)
    const disruptive = Object.keys(changes).filter(name => CRITICAL.has(name))
    if (disruptive.length && !await confirmDialog("Review configuration", `These options may affect your controller address, credentials or storage: ${disruptive.join(", ")}. Make sure you can recover access.`, "Save anyway")) return false
    this.busy = true
    try {
      await this.context.api.send("/settings/save", "POST", { changes, revision: this.data.revision })
      this.pendingRestart = true
      this.context.notify("Configuration saved. Restart to apply.", "success")
      this.data = await this.context.api.get<Snapshot>("/settings/view")
      this.draft.clear()
      return true
    } catch (error) {
      this.context.notify(error instanceof Error ? error.message : String(error), "error")
      return false
    } finally { this.busy = false; this.render() }
  }

  private async restart(): Promise<void> {
    if (this.draft.size) { this.context.notify("Save or reset pending edits before restarting.", "warning"); return }
    if (!await confirmDialog("Restart controller?", "Active sessions and terminals may disconnect while the controller gracefully shuts down and starts again.", "Restart")) return
    this.busy = true
    try {
      await this.context.api.send("/settings/restart", "POST", {})
      const notice = this.root.querySelector<HTMLElement>(".settings-notice")
      if (notice) notice.textContent = "Restart requested. Checking server availability…"
      const running = this.data?.running
      const { port: nextPort, uiPath: nextPath } = nextRestartSettings(this.data)
      const url = new URL(restartDestination(window.location.href, running?.port ?? 0, nextPort, nextPath))
      let attempt = 0
      const poll = async () => {
        attempt++
        try {
          const response = await fetch(new URL("/readyz", url.origin), {
            cache: "no-store", mode: url.origin === window.location.origin ? "cors" : "no-cors",
          })
          if ((response.ok || response.type === "opaque") && attempt >= 7) { window.location.assign(url.href); return }
        } catch { /* Controller may be offline during restart. */ }
        if (attempt < 35) window.setTimeout(() => { void poll() }, 1200)
        else if (notice) notice.textContent = `The controller is still unreachable. Check the configuration and open ${url.origin}${url.pathname} manually.`
      }
      window.setTimeout(() => { void poll() }, 2000)
    } catch (error) { this.context.notify(error instanceof Error ? error.message : String(error), "error"); this.busy = false }
  }
}
