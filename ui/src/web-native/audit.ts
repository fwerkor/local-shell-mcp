import { AUDIT_OPERATIONS, auditInput, auditOutput, formatAuditValue, selectionAfterRefresh } from "../audit-utils"
import type { AuditEntry, AuditPayload } from "../types"
import {
  BaseController,
  button,
  copyText,
  escapeHtml,
  highlightedHtml,
  queryString,
  rgbaCanvas,
  statusClass,
  type NativePageContext,
} from "./common"

const AUDIT_TIME_RANGES = [
  { label: "15m", seconds: 15 * 60 },
  { label: "1h", seconds: 60 * 60 },
  { label: "24h", seconds: 24 * 60 * 60 },
  { label: "7d", seconds: 7 * 24 * 60 * 60 },
  { label: "All", seconds: 0 },
]

export class AuditController extends BaseController {
  private entries: AuditEntry[] = []
  private selected = 0
  private detail: AuditEntry | null = null
  private loading = false
  private paused = false
  private renderedDetailId: string | undefined
  private refreshQueued = false
  private preserveSelectionOnQueuedRefresh = false
  private totalMatched = 0
  private detailRequest = 0
  private filterTimer: number | null = null
  private filters = { node: "", operation: "", time: "24h", sort: "desc", search: "", event: "", session: "" }

  mount(root: HTMLElement): void {
    this.root = root
    this.root.innerHTML = `<section class="native-page audit-page"><div class="audit-searchbar"><label>Search audit<input type="search" data-filter="search" placeholder="Command, path, tool, error…" autocomplete="off"/></label><div class="toolbar-actions"><button class="native-button" type="button" data-action="toggle-live" aria-pressed="false">Pause updates</button></div></div><div class="audit-filter-strip"><label><span>Node</span><select data-filter="node"></select></label><label><span>Operation</span><select data-filter="operation"></select></label><label><span>Time</span><select data-filter="time"></select></label><label><span>Sort</span><select data-filter="sort"><option value="desc">Newest first</option><option value="asc">Oldest first</option></select></label><div class="audit-filter-actions">${button("Advanced", "toggle-advanced")}</div></div><div class="audit-advanced" data-role="advanced" hidden><label>Event<input data-filter="event" placeholder="tool_call_completed"/></label><label>Session<input data-filter="session" placeholder="session id"/></label><button class="native-button" type="button" data-action="clear-filters">Clear filters</button></div><div class="audit-layout"><section class="native-panel audit-list-panel"><header><div><h3>Audit records</h3><p data-role="audit-summary">Loading…</p></div><div class="panel-tools"><button class="native-button" type="button" data-action="previous-record" disabled>Previous</button><button class="native-button" type="button" data-action="next-record" disabled>Next</button></div></header><div class="audit-list" data-role="audit-list" tabindex="0" aria-label="Audit records. Use up and down arrows to select a record."><div class="native-loading">Loading audit records…</div></div></section><section class="native-panel audit-detail-panel"><header><div><h3 data-role="audit-title">Call details</h3><p data-role="audit-meta">Select a record</p></div><div class="status-chip neutral" data-role="audit-status">EVENT</div></header><div class="audit-details" data-role="audit-detail"><div class="native-empty">No record selected</div></div></section></div></section>`
    this.populateFilters()
    this.listen(root, "click", (event) => this.onClick(event))
    this.listen(root, "change", (event) => this.onFilterChange(event))
    this.listen(root, "input", (event) => this.onFilterInput(event))
    this.listen(root, "keydown", (event) => {
      const key = event as KeyboardEvent
      if (!(key.target instanceof HTMLElement) || !key.target.closest("[data-role=audit-list]")) return
      if (key.key === "ArrowDown" || key.key === "ArrowUp") {
        key.preventDefault()
        this.moveSelection(key.key === "ArrowDown" ? 1 : -1)
      }
    })
    this.every(() => { if (!this.paused) void this.refresh() }, 5_000)
    void this.refresh()
  }

  private populateFilters(): void {
    const node = this.root.querySelector<HTMLSelectElement>("[data-filter=node]")
    if (node) node.innerHTML = `<option value="">All</option>${this.context.machines().map((machine) => `<option value="${escapeHtml(machine.name)}">${escapeHtml(machine.name)}</option>`).join("")}`
    const operation = this.root.querySelector<HTMLSelectElement>("[data-filter=operation]")
    if (operation) operation.innerHTML = AUDIT_OPERATIONS.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value || "All")}</option>`).join("")
    const time = this.root.querySelector<HTMLSelectElement>("[data-filter=time]")
    if (time) time.innerHTML = AUDIT_TIME_RANGES.map((item) => `<option value="${item.label}"${item.label === this.filters.time ? " selected" : ""}>${item.label}</option>`).join("")
  }

  async refresh(preserveSelection = false): Promise<void> {
    if (this.loading) {
      this.refreshQueued = true
      this.preserveSelectionOnQueuedRefresh ||= preserveSelection
      return
    }
    this.loading = true
    const requestedFilters = { ...this.filters }
    const filtersChanged = () => Object.entries(requestedFilters).some(
      ([key, value]) => this.filters[key as keyof typeof this.filters] !== value,
    )
    try {
      const range = AUDIT_TIME_RANGES.find((item) => item.label === requestedFilters.time) || AUDIT_TIME_RANGES[2]!
      const payload = await this.context.api.get<AuditPayload>(`/audit${queryString({ limit: 800, node: requestedFilters.node, operation: requestedFilters.operation, search: requestedFilters.search, event: requestedFilters.event, session: requestedFilters.session, start_ts: range.seconds ? Date.now() / 1000 - range.seconds : undefined, sort: requestedFilters.sort })}`)
      if (this.destroyed || filtersChanged()) return
      const nextSelected = selectionAfterRefresh(
        this.entries,
        this.selected,
        payload.entries,
        !preserveSelection,
      )
      this.entries = payload.entries
      this.totalMatched = payload.total_matched
      this.selected = nextSelected
      this.loading = false
      this.renderList()
      void this.loadDetail()
    } catch (error) {
      if (this.destroyed || filtersChanged()) return
      this.context.notify(`Audit: ${error instanceof Error ? error.message : String(error)}`, "error")
      if (!this.entries.length) {
        const list = this.root.querySelector<HTMLElement>("[data-role=audit-list]")
        if (list) list.innerHTML = '<div class="native-error">Unable to load audit records. Use Refresh to retry.</div>'
      }
    } finally {
      this.loading = false
      if (this.refreshQueued && !this.destroyed) {
        this.refreshQueued = false
        const preserveQueuedSelection = this.preserveSelectionOnQueuedRefresh
        this.preserveSelectionOnQueuedRefresh = false
        void this.refresh(preserveQueuedSelection)
      }
    }
  }

  private renderList(): void {
    const summary = this.root.querySelector<HTMLElement>("[data-role=audit-summary]")
    if (summary) summary.textContent = `${this.entries.length} shown / ${this.totalMatched} matching · ${this.paused ? "updates paused" : "live"}`
    const list = this.root.querySelector<HTMLElement>("[data-role=audit-list]")
    const previous = this.root.querySelector<HTMLButtonElement>("[data-action=previous-record]")
    const next = this.root.querySelector<HTMLButtonElement>("[data-action=next-record]")
    if (previous) previous.disabled = !this.entries.length || this.selected <= 0
    if (next) next.disabled = !this.entries.length || this.selected >= this.entries.length - 1
    if (!list) return
    if (!this.entries.length) {
      list.innerHTML = '<div class="native-empty"><strong>No matching audit records</strong><span>Adjust filters or wait for MCP activity.</span></div>'
      this.detail = null
      this.renderDetail()
      return
    }
    list.innerHTML = `<table class="native-table audit-table"><thead><tr><th>Time</th><th>Node</th><th>Operation</th><th>Event / Tool</th><th>Status</th></tr></thead><tbody>${this.entries.map((entry, index) => {
      const status = entry.paired === false ? entry.status === "running" ? "RUNNING" : "UNPAIRED" : entry.ok === false || entry.error || entry.status === "failed" ? "FAILED" : entry.ok === true || entry.status === "success" ? "SUCCESS" : String(entry.status || "EVENT").toUpperCase()
      return `<tr class="${index === this.selected ? "selected" : ""}" data-audit-index="${index}" aria-selected="${index === this.selected}"><td title="${escapeHtml(new Date(entry.ts * 1000).toLocaleString())}">${new Date(entry.ts * 1000).toLocaleTimeString()}</td><td>${escapeHtml(entry.node)}</td><td><span class="operation-label">${escapeHtml(entry.operation)}</span></td><td><strong>${escapeHtml(entry.tool || entry.event)}</strong><small>${entry.command ? escapeHtml(entry.command.slice(0, 90)) : escapeHtml(entry.session || "")}</small></td><td><span class="status-chip ${statusClass(status)}">${escapeHtml(status)}</span></td></tr>`
    }).join("")}</tbody></table>`
  }

  private async loadDetail(): Promise<void> {
    const current = this.entries[this.selected]
    const request = ++this.detailRequest
    const detailMatchesCurrent = Boolean(current?.id && this.detail?.id === current.id)
    if (!detailMatchesCurrent) {
      this.detail = null
      this.renderDetail()
    }
    if (!current?.id) {
      return
    }
    try {
      const detail = await this.context.api.get<AuditEntry>(`/audit/detail${queryString({ id: current.id, columns: 120, rows: 50, cell_aspect: 2 })}`)
      if (request !== this.detailRequest || this.destroyed) return
      this.detail = detail
      this.renderDetail()
    } catch (error) {
      if (request !== this.detailRequest || this.destroyed) return
      this.context.notify(`Audit detail: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private displayedEntry(): AuditEntry | undefined {
    const current = this.entries[this.selected]
    return this.detail && this.detail.id === current?.id ? this.detail : current
  }

  private renderDetail(): void {
    const entry = this.displayedEntry()
    const target = this.root.querySelector<HTMLElement>("[data-role=audit-detail]")
    const title = this.root.querySelector<HTMLElement>("[data-role=audit-title]")
    const meta = this.root.querySelector<HTMLElement>("[data-role=audit-meta]")
    const statusElement = this.root.querySelector<HTMLElement>("[data-role=audit-status]")
    if (!target) return
    if (!entry) {
      if (title) title.textContent = "Call details"
      if (meta) meta.textContent = "Select a record"
      this.renderedDetailId = undefined
      if (statusElement) { statusElement.textContent = "EVENT"; statusElement.className = "status-chip neutral" }
      target.innerHTML = '<div class="native-empty">No record selected</div>'
      return
    }
    const status = entry.paired === false ? entry.status === "running" ? "RUNNING" : "UNPAIRED" : entry.ok === false || entry.error || entry.status === "failed" ? "FAILED" : entry.ok === true || entry.status === "success" ? "SUCCESS" : String(entry.status || "EVENT").toUpperCase()
    if (title) title.textContent = entry.tool || entry.event
    if (meta) meta.textContent = `${new Date(entry.ts * 1000).toLocaleString()} · ${entry.node}${typeof entry.duration_ms === "number" ? ` · ${entry.duration_ms < 1000 ? `${entry.duration_ms} ms` : `${(entry.duration_ms / 1000).toFixed(2)} s`}` : ""}`
    if (statusElement) {
      statusElement.className = `status-chip ${statusClass(status)}`
      statusElement.textContent = status
    }
    const output = formatAuditValue(auditOutput(entry), "No return value recorded")
    const input = formatAuditValue(auditInput(entry), "No input recorded")
    const scrollPositions = this.renderedDetailId === entry.id
      ? Array.from(target.querySelectorAll<HTMLElement>(".audit-value")).map((element) => [element.scrollTop, element.scrollLeft])
      : []
    this.renderedDetailId = entry.id
    target.innerHTML = `<section class="audit-detail-card result"><header><h4>Call result</h4><button type="button" data-copy-detail="output">Copy</button></header><div class="audit-value" data-role="audit-output">${entry.image_preview?.kind === "image" ? '<div class="audit-image-stage" data-role="audit-image"></div>' : `<pre><code>${highlightedHtml(output, "result.json")}</code></pre>`}</div></section><section class="audit-detail-card input"><header><h4>Call input</h4><button type="button" data-copy-detail="input">Copy</button></header><div class="audit-value"><pre><code>${highlightedHtml(input, "input.json")}</code></pre></div></section>`
    target.querySelectorAll<HTMLElement>(".audit-value").forEach((element, index) => {
      element.scrollTop = scrollPositions[index]?.[0] || 0
      element.scrollLeft = scrollPositions[index]?.[1] || 0
    })
    if (entry.image_preview?.kind === "image") {
      const stage = target.querySelector<HTMLElement>("[data-role=audit-image]")
      const canvas = rgbaCanvas(entry.image_preview)
      if (stage && canvas) {
        stage.appendChild(canvas)
        const metadata = document.createElement("small")
        metadata.textContent = String(entry.image_preview.path || "Image result")
        stage.appendChild(metadata)
      } else if (stage) stage.textContent = entry.image_preview_error || "Unable to decode image result"
    }
  }

  private scheduleFilterRefresh(): void {
    if (this.filterTimer !== null) window.clearTimeout(this.filterTimer)
    this.filterTimer = window.setTimeout(() => {
      this.filterTimer = null
      void this.refresh(true)
    }, 250)
  }

  private moveSelection(delta: number): void {
    if (!this.entries.length) return
    const next = Math.max(0, Math.min(this.entries.length - 1, this.selected + delta))
    if (next === this.selected) return
    this.selected = next
    this.renderList()
    this.root.querySelector<HTMLElement>(`[data-audit-index="${next}"]`)?.scrollIntoView({ block: "nearest" })
    void this.loadDetail()
  }

  private onClick(event: MouseEvent): void {
    const target = event.target as HTMLElement
    const index = target.closest<HTMLElement>("[data-audit-index]")?.dataset.auditIndex
    if (index !== undefined) {
      this.selected = Number(index)
      this.renderList()
      void this.loadDetail()
      return
    }
    const copy = target.closest<HTMLElement>("[data-copy-detail]")?.dataset.copyDetail
    if (copy) {
      const entry = this.displayedEntry()
      if (!entry) return
      const value = copy === "output" ? formatAuditValue(auditOutput(entry), "No return value recorded") : formatAuditValue(auditInput(entry), "No input recorded")
      void copyText(value).then((copied) => this.context.notify(copied ? "Audit detail copied" : "Copy failed", copied ? "success" : "error"))
      return
    }
    const action = target.closest<HTMLElement>("[data-action]")?.dataset.action
    if (action === "toggle-live") {
      this.paused = !this.paused
      const control = target.closest<HTMLButtonElement>("[data-action=toggle-live]")
      if (control) { control.textContent = this.paused ? "Resume updates" : "Pause updates"; control.setAttribute("aria-pressed", String(this.paused)) }
      this.renderList()
      if (!this.paused) void this.refresh(true)
    } else if (action === "previous-record") this.moveSelection(-1)
    else if (action === "next-record") this.moveSelection(1)
    else if (action === "toggle-advanced") {
      const advanced = this.root.querySelector<HTMLElement>("[data-role=advanced]")
      if (advanced) {
        advanced.hidden = !advanced.hidden
        target.closest("button")?.setAttribute("aria-expanded", String(!advanced.hidden))
      }
    } else if (action === "clear-filters") {
      this.filters = { node: "", operation: "", time: "24h", sort: "desc", search: "", event: "", session: "" }
      this.root.querySelectorAll<HTMLInputElement | HTMLSelectElement>("[data-filter]").forEach((control) => { control.value = this.filters[control.dataset.filter as keyof typeof this.filters] })
      void this.refresh(true)
    }
  }

  private onFilterChange(event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLSelectElement) || !target.dataset.filter) return
    const key = target.dataset.filter as keyof typeof this.filters
    this.filters[key] = target.value
    void this.refresh(true)
  }

  private onFilterInput(event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement) || !target.dataset.filter) return
    const key = target.dataset.filter as keyof typeof this.filters
    this.filters[key] = target.value
    this.scheduleFilterRefresh()
  }

  destroy(): void {
    if (this.filterTimer !== null) window.clearTimeout(this.filterTimer)
    this.filterTimer = null
    super.destroy()
  }
}

