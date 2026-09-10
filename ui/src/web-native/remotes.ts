import type { InvitePayload, Machine, MachinePayload } from "../types"
import {
  BaseController,
  button,
  confirmDialog,
  copyText,
  escapeHtml,
  formatAge,
  highlightedHtml,
  openFormDialog,
  statusClass,
  type NativePageContext,
} from "./common"

function remoteDetailRevision(machine: Machine): string {
  return JSON.stringify([
    machine.name,
    machine.status,
    machine.workdir,
    machine.capabilities,
    machine.info,
  ])
}

export class RemotesController extends BaseController {
  private machines: Machine[] = []
  private selected = 0
  private enabled = true
  private loading = false
  private renderedDetailRevision = ""

  mount(root: HTMLElement): void {
    this.root = root
    this.root.innerHTML = `<section class="native-page remotes-page"><div class="remote-summary" data-role="remote-summary"></div><div class="native-toolbar"><div><strong>Remote workers</strong><span class="toolbar-detail">Persistent worker identities and one-time invitations</span></div><div class="toolbar-actions">${button("New invite", "invite", { icon: "+", primary: true })}${button("Rename", "rename", { disabled: true })}${button("Revoke", "revoke", { danger: true, disabled: true })}</div></div><div class="remotes-layout"><section class="native-panel remote-list-panel"><header><div><h3>Remote nodes</h3><p data-role="remote-count">Loading…</p></div></header><div data-role="remote-list"><div class="native-loading">Loading remote nodes…</div></div></section><section class="native-panel remote-detail-panel"><header><div><h3>Node details</h3><p>Version, workdir, capabilities, and system information</p></div></header><div class="remote-detail" data-role="remote-detail"><div class="native-empty">No node selected</div></div></section></div></section>`
    this.listen(root, "click", (event) => this.onClick(event))
    this.listen(root, "keydown", (event) => this.onListKeyDown(event as KeyboardEvent))
    void this.refresh()
  }

  async refresh(): Promise<void> {
    if (this.loading) return
    this.loading = true
    try {
      const payload = await this.context.api.get<MachinePayload>("/remotes")
      if (this.destroyed) return
      const selectedName = this.machines[this.selected]?.name
      this.machines = payload.machines
      this.enabled = payload.enabled !== false
      this.selected = Math.max(0, selectedName ? this.machines.findIndex((machine) => machine.name === selectedName) : 0)
      if (this.selected < 0) this.selected = 0
      this.render()
    } catch (error) {
      this.context.notify(`Remotes: ${error instanceof Error ? error.message : String(error)}`, "error")
    } finally {
      this.loading = false
    }
  }

  private current(): Machine | undefined {
    return this.machines[this.selected]
  }

  private render(): void {
    const focusedName = document.activeElement instanceof HTMLElement && this.root.contains(document.activeElement)
      ? document.activeElement.closest<HTMLElement>("[data-remote-name]")?.dataset.remoteName
      : undefined
    const online = this.machines.filter((machine) => machine.status === "online").length
    const offline = this.machines.length - online
    const summary = this.root.querySelector<HTMLElement>("[data-role=remote-summary]")
    if (summary) summary.innerHTML = [
      ["Online", online, "success"], ["Offline", offline, offline ? "warning" : "neutral"], ["Total", this.machines.length, "accent"], ["Controller", this.enabled ? "READY" : "DISABLED", this.enabled ? "info" : "warning"],
    ].map(([label, value, tone]) => `<article class="summary-card ${tone}"><span>${label}</span><strong>${value}</strong></article>`).join("")
    const count = this.root.querySelector<HTMLElement>("[data-role=remote-count]")
    if (count) count.textContent = this.enabled ? `${online} online · ${offline} offline` : "Remote worker support is disabled"
    const list = this.root.querySelector<HTMLElement>("[data-role=remote-list]")
    if (list) {
      list.innerHTML = this.machines.length ? `<table class="native-table remote-table" role="grid" aria-label="Remote workers"><thead><tr><th>State</th><th>Name</th><th>Version</th><th>Workdir</th><th>Last seen</th></tr></thead><tbody>${this.machines.map((machine, index) => {
        const selected = index === this.selected
        return `<tr class="${selected ? "selected" : ""}" data-remote-index="${index}" data-remote-name="${escapeHtml(machine.name)}" tabindex="${selected ? "0" : "-1"}" aria-selected="${selected}" aria-label="Remote worker ${escapeHtml(machine.name)}, ${escapeHtml(machine.status)}"><td><span class="status-chip ${statusClass(machine.status)}">${escapeHtml(machine.status)}</span></td><td><strong>${escapeHtml(machine.name)}</strong></td><td>${escapeHtml(String(machine.info?.version || machine.info?.lsm_version || "unknown"))}</td><td><code>${escapeHtml(machine.workdir || "—")}</code></td><td>${formatAge(machine.last_seen, machine.last_seen_age_s)}</td></tr>`
      }).join("")}</tbody></table>` : `<div class="native-empty"><strong>${this.enabled ? "No remote nodes" : "Remotes disabled"}</strong><span>${this.enabled ? "Create a one-time invitation to attach a worker." : "Enable remote workers in server configuration."}</span></div>`
      if (focusedName) {
        const focusedIndex = this.machines.findIndex((machine) => machine.name === focusedName)
        if (focusedIndex >= 0) this.focusRemote(focusedIndex)
      }
    }
    const current = this.current()
    const detail = this.root.querySelector<HTMLElement>("[data-role=remote-detail]")
    if (detail) {
      const revision = current ? remoteDetailRevision(current) : "empty"
      if (revision !== this.renderedDetailRevision) {
        this.renderedDetailRevision = revision
        detail.innerHTML = current ? `<div class="remote-title"><span class="status-dot ${current.status === "online" ? "online" : "offline"}"></span><div><h2>${escapeHtml(current.name)}</h2><p>${escapeHtml(current.status)}</p></div></div><dl class="detail-grid"><div><dt>LSM version</dt><dd>${escapeHtml(String(current.info?.version || current.info?.lsm_version || "unknown"))}</dd></div><div><dt>Last seen</dt><dd data-role="remote-last-seen"></dd></div><div><dt>Workdir</dt><dd><code>${escapeHtml(current.workdir || "—")}</code></dd></div><div><dt>Capabilities</dt><dd>${(current.capabilities || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("") || "—"}</dd></div></dl><section class="detail-json"><h4>System information</h4><pre>${highlightedHtml(JSON.stringify(current.info || {}, null, 2), "info.json")}</pre></section>` : '<div class="native-empty">No node selected</div>'
      }
      const lastSeen = detail.querySelector<HTMLElement>("[data-role=remote-last-seen]")
      if (lastSeen && current) lastSeen.textContent = formatAge(current.last_seen, current.last_seen_age_s)
    }
    const rename = this.root.querySelector<HTMLButtonElement>("[data-action=rename]")
    const revoke = this.root.querySelector<HTMLButtonElement>("[data-action=revoke]")
    const invite = this.root.querySelector<HTMLButtonElement>("[data-action=invite]")
    if (rename) rename.disabled = !current || !this.enabled
    if (revoke) revoke.disabled = !current || !this.enabled
    if (invite) invite.disabled = !this.enabled
  }

  private async invite(): Promise<void> {
    const values = await openFormDialog({ title: "Create remote invite", detail: "The command can be used once and expires automatically.", fields: [{ name: "name", label: "Preferred name", placeholder: "build-host" }, { name: "workdir", label: "Working directory", placeholder: "/workspace" }, { name: "ttl", label: "Lifetime (seconds)", value: "600", type: "number" }], submitLabel: "Create invite" })
    if (!values) return
    try {
      const invite = await this.context.api.send<InvitePayload>("/remotes", "POST", { name: values.name.trim() || undefined, workdir: values.workdir.trim() || undefined, ttl_s: Number(values.ttl) || 600 })
      await this.showInvite(invite)
      await this.refresh()
    } catch (error) {
      this.context.notify(`Invite: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private async showInvite(invite: InvitePayload): Promise<void> {
    return new Promise((resolve) => {
      const overlay = document.createElement("div")
      overlay.className = "native-dialog-overlay"
      overlay.innerHTML = `<section class="native-dialog wide invite-dialog"><header><div><h2>Remote join command</h2><p>Run this command on the remote node.</p></div><button type="button" data-close>×</button></header><div class="native-dialog-body"><div class="invite-command"><code>${escapeHtml(invite.command)}</code><button class="native-button primary" type="button" data-copy>Copy command</button></div><small>Expires ${new Date(invite.expires_at * 1000).toLocaleString()}</small></div><footer><button class="native-button" type="button" data-close>Close</button></footer></section>`
      document.body.appendChild(overlay)
      const close = () => { overlay.remove(); resolve() }
      overlay.querySelectorAll<HTMLElement>("[data-close]").forEach((element) => element.addEventListener("click", close))
      overlay.querySelector<HTMLElement>("[data-copy]")?.addEventListener("click", async (event) => {
        const copied = await copyText(invite.command)
        ;(event.currentTarget as HTMLElement).textContent = copied ? "Copied" : "Copy failed"
      })
    })
  }

  private async rename(): Promise<void> {
    const current = this.current()
    if (!current) return
    const values = await openFormDialog({ title: `Rename ${current.name}`, fields: [{ name: "name", label: "New name", value: current.name, required: true }], submitLabel: "Rename" })
    const name = values?.name.trim()
    if (!name || name === current.name) return
    try {
      await this.context.api.send("/remotes/rename", "POST", { machine: current.name, new_name: name })
      this.context.notify(`Renamed ${current.name} to ${name}`, "success")
      await this.refresh()
      await this.context.refreshChrome()
    } catch (error) {
      this.context.notify(`Rename: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private async revoke(): Promise<void> {
    const current = this.current()
    if (!current || !await confirmDialog(`Revoke ${current.name}?`, "Its persistent identity will no longer reconnect.", "Revoke worker")) return
    try {
      await this.context.api.send("/remotes/revoke", "POST", { machine: current.name })
      this.selected = Math.max(0, this.selected - 1)
      this.context.notify(`Revoked ${current.name}`, "success")
      await this.refresh()
      await this.context.refreshChrome()
    } catch (error) {
      this.context.notify(`Revoke: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private onClick(event: MouseEvent): void {
    const target = event.target as HTMLElement
    const index = target.closest<HTMLElement>("[data-remote-index]")?.dataset.remoteIndex
    if (index !== undefined) {
      this.selected = Number(index)
      this.render()
      return
    }
    const action = target.closest<HTMLElement>("[data-action]")?.dataset.action
    if (action === "invite") void this.invite()
    else if (action === "rename") void this.rename()
    else if (action === "revoke") void this.revoke()
  }

  private focusRemote(index: number): void {
    this.root.querySelector<HTMLElement>(`[data-remote-index="${index}"]`)?.focus()
  }

  private selectRemote(index: number, focus = false): void {
    const next = Math.max(0, Math.min(this.machines.length - 1, index))
    if (!this.machines[next]) return
    this.selected = next
    this.render()
    if (focus) this.focusRemote(next)
  }

  private onListKeyDown(event: KeyboardEvent): void {
    const row = (event.target as HTMLElement).closest<HTMLElement>("[data-remote-index]")
    const rawIndex = row?.dataset.remoteIndex
    if (rawIndex === undefined) return
    const index = Number(rawIndex)
    let nextIndex: number | null = null
    if (event.key === "ArrowDown") nextIndex = Math.min(this.machines.length - 1, index + 1)
    else if (event.key === "ArrowUp") nextIndex = Math.max(0, index - 1)
    else if (event.key === "Home") nextIndex = 0
    else if (event.key === "End") nextIndex = this.machines.length - 1
    else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      this.selectRemote(index, true)
      return
    }
    if (nextIndex === null) return
    event.preventDefault()
    this.selectRemote(nextIndex, true)
  }
}

