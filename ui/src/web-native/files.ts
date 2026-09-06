import type { FileEntry, FilePreview, FilesPayload, Machine } from "../types"
import {
  BaseController,
  basename,
  button,
  confirmDialog,
  escapeHtml,
  fileIcon,
  formatBytes,
  formatDate,
  highlightedHtml,
  joinPath,
  openFormDialog,
  queryString,
  rgbaCanvas,
  type NativePageContext,
} from "./common"

export function fileBreadcrumbRows(path: string): Array<{ label: string; path: string }> {
  const windows = path.includes("\\") && !path.includes("/")
  const separator = windows ? "\\" : "/"
  const unc = windows ? path.match(/^\\\\[^\\]+\\[^\\]+/)?.[0] : undefined
  const drive = unc || (windows ? path.match(/^[A-Za-z]:/)?.[0] : path.startsWith("/") ? "/" : "")
  const parts = path.slice(drive ? drive.length : 0).replace(/^[\\/]+/, "").split(/[\\/]/).filter(Boolean)
  const rows: Array<{ label: string; path: string }> = []
  if (drive) rows.push({ label: drive, path: drive === "/" || unc ? drive : `${drive}\\` })
  let current = drive === "/" ? "/" : drive ? (unc ? drive : `${drive}\\`) : "."
  for (const part of parts) {
    current = current === "." ? part : current === "/" ? `/${part}` : `${current.replace(/[\\/]$/, "")}${separator}${part}`
    rows.push({ label: part, path: current })
  }
  if (!rows.length) rows.push({ label: ".", path: "." })
  return rows
}

export type FileSort = "name" | "size" | "modified"

export function filterAndSortFileEntries(
  entries: FileEntry[],
  query: string,
  sort: FileSort,
  direction: "asc" | "desc",
): FileEntry[] {
  const needle = query.trim().toLocaleLowerCase()
  const visible = needle ? entries.filter((entry) => entry.name.toLocaleLowerCase().includes(needle)) : [...entries]
  const sign = direction === "asc" ? 1 : -1
  return visible.sort((left, right) => {
    if (left.type === "dir" && right.type !== "dir") return -1
    if (left.type !== "dir" && right.type === "dir") return 1
    let result = 0
    if (sort === "size") result = Number(left.size || 0) - Number(right.size || 0)
    else if (sort === "modified") result = Number(left.modified || 0) - Number(right.modified || 0)
    else result = left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" })
    return result === 0 ? left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" }) : result * sign
  })
}

export class FilesController extends BaseController {
  private machine = "local"
  private path = "."
  private payload: FilesPayload | null = null
  private preview: FilePreview | null = null
  private selectedPath: string | null = null
  private showHidden = false
  private query = ""
  private sort: FileSort = "name"
  private sortDirection: "asc" | "desc" = "asc"
  private previewVisible = true
  private busy = false
  private refreshQueued = false
  private clipboard: { mode: "copy" | "move"; machine: string; path: string } | null = null
  private pendingSelectionPath: string | null = null
  private previewRequest = 0

  mount(root: HTMLElement): void {
    this.root = root
    this.machine = this.context.machines().some((item) => item.name === "local") ? "local" : this.context.machines()[0]?.name || "local"
    this.renderShell()
    this.listen(root, "click", (event) => this.onClick(event))
    this.listen(root, "dblclick", (event) => this.onDoubleClick(event))
    this.listen(root, "change", (event) => this.onChange(event))
    this.listen(root, "input", (event) => this.onInput(event))
    this.listen(root, "keydown", (event) => this.onListKeyDown(event as KeyboardEvent))
    void this.refresh()
  }

  private machines(): Machine[] {
    return this.context.machines()
  }

  private entries(): FileEntry[] {
    const entries = (this.payload?.entries || []).filter((entry) => this.showHidden || !entry.hidden)
    return filterAndSortFileEntries(entries, this.query, this.sort, this.sortDirection)
  }

  private current(): FileEntry | undefined {
    return this.entries().find((entry) => entry.path === this.selectedPath) || this.entries()[0]
  }

  private renderShell(): void {
    this.root.innerHTML = `<section class="native-page files-page">
      <div class="native-toolbar files-toolbar">
        <div class="toolbar-group compact-only"><label>Machine<select data-role="machine"></select></label></div>
        <div class="path-bar"><button class="native-button icon-only" type="button" data-action="parent" title="Parent directory (Alt+Up)" aria-label="Parent directory">↑</button><div class="breadcrumbs" data-role="breadcrumbs"></div><input data-role="path" aria-label="Path" value="${escapeHtml(this.path)}" title="Focus path with Ctrl+L"/></div>
        <div class="toolbar-actions" data-role="actions"></div>
      </div>
      <div class="files-controlbar">
        <label class="file-search"><span aria-hidden="true">⌕</span><input data-role="file-search" type="search" placeholder="Filter this folder" autocomplete="off"/><kbd>Ctrl F</kbd></label>
        <label>Sort<select data-role="file-sort"><option value="name">Name</option><option value="modified">Modified</option><option value="size">Size</option></select></label>
        <button class="native-button icon-only" type="button" data-action="sort-direction" title="Reverse sort" aria-label="Reverse sort">↕</button>
        <label class="native-toggle"><input data-role="hidden" type="checkbox"/>Hidden</label>
        <span class="file-clipboard" data-role="clipboard-state">Clipboard empty</span>
      </div>
      <div class="files-layout preview-open">
        <aside class="native-panel machine-rail"><header><div><h3>Locations</h3><p>Connected workspaces</p></div><span data-role="machine-count">${this.machines().length}</span></header><div class="machine-list" data-role="machines"></div><div class="file-shortcuts"><button type="button" data-action="home-location">⌂ <span>Workspace</span></button><button type="button" data-action="parent">↑ <span>Parent folder</span></button></div></aside>
        <section class="native-panel file-parent-panel" hidden><header><div><h3>Parent</h3><p data-role="parent-summary">Loading…</p></div></header><div class="file-parent-list" data-role="parent-list"><div class="native-loading">Loading parent directory…</div></div></section>
        <section class="native-panel file-list-panel"><header><div><h3>Files</h3><p data-role="directory-summary">Loading…</p></div><div class="panel-tools"><button class="native-button" type="button" data-action="refresh">Refresh</button></div></header><div class="file-table-wrap" data-role="file-list"><div class="native-loading">Loading directory…</div></div><footer class="file-statusbar"><span data-role="selection-summary">No selection</span><span>Enter open · F2 rename · Del delete</span></footer></section>
        <section class="native-panel file-preview-panel"><header><div><h3>Preview</h3><p data-role="preview-summary">Choose an entry</p></div></header><div class="file-preview" data-role="preview"><div class="native-empty">No selection</div></div></section>
      </div>
      <input data-role="file-upload" type="file" multiple hidden/>
    </section>`
    this.renderMachines()
    this.renderBreadcrumbs()
    this.renderActions()
  }

  private renderMachines(): void {
    const machines = this.machines()
    const list = this.root.querySelector<HTMLElement>("[data-role=machines]")
    const select = this.root.querySelector<HTMLSelectElement>("[data-role=machine]")
    const count = this.root.querySelector<HTMLElement>("[data-role=machine-count]")
    if (count) count.textContent = String(machines.length)
    if (list) list.innerHTML = machines.map((machine) => `<button type="button" class="machine-row ${machine.name === this.machine ? "active" : ""}" data-machine="${escapeHtml(machine.name)}"><span class="status-dot ${machine.status === "online" ? "online" : "offline"}"></span><span><strong>${escapeHtml(machine.name)}</strong><small>${escapeHtml(machine.workdir || machine.status)}</small></span></button>`).join("")
    if (select) select.innerHTML = machines.map((machine) => `<option value="${escapeHtml(machine.name)}"${machine.name === this.machine ? " selected" : ""}>${escapeHtml(machine.name)}</option>`).join("")
  }

  private renderBreadcrumbs(): void {
    const target = this.root.querySelector<HTMLElement>("[data-role=breadcrumbs]")
    const input = this.root.querySelector<HTMLInputElement>("[data-role=path]")
    if (input && input.value !== this.path) input.value = this.path
    if (!target) return
    const rows = fileBreadcrumbRows(this.path)
    target.innerHTML = rows.map((row, index) => `${index ? '<span class="crumb-separator">›</span>' : ""}<button type="button" data-path="${escapeHtml(row.path)}">${escapeHtml(row.label)}</button>`).join("")
  }

  private renderActions(): void {
    const current = this.current()
    const ready = this.payload !== null
    const target = this.root.querySelector<HTMLElement>("[data-role=actions]")
    const parent = this.root.querySelector<HTMLButtonElement>("[data-action=parent]")
    if (parent) parent.disabled = !this.payload?.parent || this.payload.parent === this.path
    if (!target) return
    target.innerHTML = [
      button("New file", "new-file", { icon: "+", disabled: !ready }),
      button("New folder", "new-dir", { icon: "▰", disabled: !ready }),
      button("Upload", "upload", { disabled: !ready }),
      button(current?.type === "dir" ? "Open folder" : "Edit file", "open", { disabled: !current }),
      button("Rename", "rename", { disabled: !current }),
      button("Copy", "copy", { disabled: !current }),
      button("Move", "cut", { disabled: !current }),
      button(this.clipboard ? `Paste ${this.clipboard.mode === "copy" ? "copy" : "move"}` : "Paste", "paste", { disabled: !ready || !this.clipboard }),
      button(this.previewVisible ? "Hide preview" : "Show preview", "toggle-preview", { disabled: !ready }),
      button("Delete", "delete", { danger: true, disabled: !current }),
    ].join("")
    const state = this.root.querySelector<HTMLElement>("[data-role=clipboard-state]")
    if (state) {
      state.textContent = this.clipboard ? `${this.clipboard.mode === "copy" ? "Copy" : "Move"}: ${basename(this.clipboard.path)}` : "Clipboard empty"
      state.classList.toggle("active", Boolean(this.clipboard))
    }
  }

  private navigate(path: string, pendingSelectionPath: string | null = null): void {
    this.path = path
    this.payload = null
    this.preview = null
    this.selectedPath = null
    this.pendingSelectionPath = pendingSelectionPath
    this.previewRequest += 1
    this.renderBreadcrumbs()
    this.renderParent()
    this.renderDirectory()
    this.renderActions()
    void this.refresh()
  }

  async refresh(): Promise<void> {
    if (this.busy) {
      this.refreshQueued = true
      return
    }
    this.busy = true
    const machines = this.machines()
    if (!machines.some((machine) => machine.name === this.machine)) {
      this.machine = machines.some((machine) => machine.name === "local") ? "local" : machines[0]?.name || "local"
      this.path = "."
      this.payload = null
      this.preview = null
      this.selectedPath = null
    }
    this.renderMachines()
    this.renderActions()
    const controller = this.controller()
    const requestedMachine = this.machine
    const requestedPath = this.path
    try {
      const payload = await this.context.api.get<FilesPayload>(`/files${queryString({ machine: requestedMachine, path: requestedPath })}`)
      if (
        controller.signal.aborted ||
        this.destroyed ||
        requestedMachine !== this.machine ||
        requestedPath !== this.path
      ) return
      this.payload = payload
      const entries = this.entries()
      if (this.pendingSelectionPath && entries.some((entry) => entry.path === this.pendingSelectionPath)) {
        this.selectedPath = this.pendingSelectionPath
        this.pendingSelectionPath = null
      } else if (!this.selectedPath || !entries.some((entry) => entry.path === this.selectedPath)) {
        this.selectedPath = entries[0]?.path || null
      }
      this.renderParent()
      this.renderDirectory()
      this.renderBreadcrumbs()
      void this.loadPreview()
    } catch (error) {
      if (requestedMachine !== this.machine || requestedPath !== this.path) return
      this.context.notify(`Files: ${error instanceof Error ? error.message : String(error)}`, "error")
      const list = this.root.querySelector<HTMLElement>("[data-role=file-list]")
      if (list) list.innerHTML = `<div class="native-error">${escapeHtml(error instanceof Error ? error.message : String(error))}</div>`
    } finally {
      controller.abort()
      this.busy = false
      this.renderActions()
      if (this.refreshQueued && !this.destroyed) {
        this.refreshQueued = false
        void this.refresh()
      }
    }
  }

  private renderParent(): void {
    const list = this.root.querySelector<HTMLElement>("[data-role=parent-list]")
    const summary = this.root.querySelector<HTMLElement>("[data-role=parent-summary]")
    const layout = this.root.querySelector<HTMLElement>(".files-layout")
    if (!this.payload) {
      layout?.classList.remove("no-parent")
      if (summary) summary.textContent = "Loading…"
      if (list) list.innerHTML = '<div class="native-loading">Loading parent directory…</div>'
      return
    }
    const entries = this.payload.parent_entries.filter((entry) => this.showHidden || !entry.hidden)
    layout?.classList.toggle("no-parent", this.payload.parent === this.path)
    if (summary) summary.textContent = this.payload?.parent === this.path ? "Root" : this.payload?.parent || "."
    if (!list) return
    if (!entries.length) {
      list.innerHTML = '<div class="native-empty">No parent entries</div>'
      return
    }
    list.innerHTML = entries.map((entry) => `<button type="button" class="parent-entry ${entry.path === this.path ? "active" : ""}" data-parent-path="${escapeHtml(entry.path)}"${entry.type !== "dir" ? " disabled" : ""}><span class="file-kind ${entry.type === "dir" ? "directory" : ""}">${fileIcon(entry)}</span><span>${escapeHtml(entry.name)}</span></button>`).join("")
  }

  private renderDirectory(): void {
    const list = this.root.querySelector<HTMLElement>("[data-role=file-list]")
    const summary = this.root.querySelector<HTMLElement>("[data-role=directory-summary]")
    if (!this.payload) {
      if (summary) summary.textContent = `${this.machine}:${this.path} · loading`
      if (list) list.innerHTML = '<div class="native-loading">Loading directory…</div>'
      this.preview = null
      this.renderPreview()
      return
    }
    const entries = this.entries()
    if (summary) summary.textContent = `${this.machine}:${this.path} · ${entries.length} visible entries`
    const selectionSummary = this.root.querySelector<HTMLElement>("[data-role=selection-summary]")
    const selected = this.current()
    if (selectionSummary) selectionSummary.textContent = selected ? `${selected.name} · ${selected.type === "dir" ? "folder" : formatBytes(selected.size)}` : "No selection"
    if (!list) return
    if (!entries.length) {
      list.innerHTML = '<div class="native-empty">This directory is empty.</div>'
      this.selectedPath = null
      this.preview = null
      this.renderPreview()
      return
    }
    list.innerHTML = `<table class="native-table file-table" role="grid" aria-label="Directory entries"><thead><tr><th>Name</th><th>Size</th><th>Modified</th></tr></thead><tbody>${entries.map((entry) => {
      const selected = entry.path === this.selectedPath
      return `<tr class="${selected ? "selected" : ""}" data-entry="${escapeHtml(entry.path)}" tabindex="${selected ? "0" : "-1"}" aria-selected="${selected}" aria-label="${escapeHtml(`${entry.type === "dir" ? "Folder" : "File"} ${entry.name}`)}"><td><span class="file-kind ${entry.type === "dir" ? "directory" : ""}">${fileIcon(entry)}</span><span class="file-name ${entry.hidden ? "hidden" : ""}">${escapeHtml(entry.name)}</span></td><td>${entry.type === "dir" ? "dir" : formatBytes(entry.size)}</td><td>${formatDate(entry.modified)}</td></tr>`
    }).join("")}</tbody></table>`
    this.renderActions()
  }

  private async loadPreview(): Promise<void> {
    const entry = this.current()
    if (!entry) {
      this.preview = null
      this.renderPreview()
      return
    }
    const request = ++this.previewRequest
    const target = this.root.querySelector<HTMLElement>("[data-role=preview]")
    if (target) target.innerHTML = '<div class="native-loading">Loading preview…</div>'
    try {
      const preview = await this.context.api.get<FilePreview>(`/files/preview${queryString({ machine: this.machine, path: entry.path, columns: 120, rows: 50, cell_aspect: 2 })}`)
      if (request !== this.previewRequest || this.destroyed || this.current()?.path !== entry.path) return
      this.preview = preview
      this.renderPreview()
    } catch (error) {
      if (request !== this.previewRequest) return
      this.preview = null
      if (target) target.innerHTML = `<div class="native-error">${escapeHtml(error instanceof Error ? error.message : String(error))}</div>`
    }
  }

  private renderPreview(): void {
    const entry = this.current()
    const preview = this.preview
    const target = this.root.querySelector<HTMLElement>("[data-role=preview]")
    const summary = this.root.querySelector<HTMLElement>("[data-role=preview-summary]")
    if (!target) return
    if (!entry) {
      if (summary) summary.textContent = "Choose an entry"
      target.innerHTML = '<div class="native-empty">No selection</div>'
      return
    }
    if (summary) summary.textContent = `${entry.name} · ${entry.type === "dir" ? "directory" : formatBytes(entry.size)}`
    if (!preview) {
      target.innerHTML = '<div class="native-empty">Preview unavailable</div>'
      return
    }
    if (preview.kind === "image") {
      target.innerHTML = `<div class="image-preview-meta"><strong>${escapeHtml(entry.name)}</strong><span>${escapeHtml(`${preview.original_width || preview.width} × ${preview.original_height || preview.height}`)}</span></div><div class="image-preview-stage" data-role="image-stage"></div>`
      const canvas = rgbaCanvas(preview)
      const stage = target.querySelector<HTMLElement>("[data-role=image-stage]")
      if (stage && canvas) stage.appendChild(canvas)
      else if (stage) stage.innerHTML = '<div class="native-error">Unable to decode image preview.</div>'
      return
    }
    if (preview.kind === "directory") {
      const rows = (preview.entries || []).filter((item) => this.showHidden || !item.hidden)
      target.innerHTML = `<div class="directory-preview"><div class="directory-preview-head"><strong>${escapeHtml(entry.name)}</strong><span>${rows.length} visible entries</span></div>${rows.slice(0, 80).map((item) => `<button type="button" data-preview-entry="${escapeHtml(item.path)}"><span>${fileIcon(item)}</span>${escapeHtml(item.name)}</button>`).join("") || '<div class="native-empty">Empty directory</div>'}</div>`
      return
    }
    const content = String(preview.content || preview.preview || "")
    target.innerHTML = `<pre class="code-preview ${preview.kind === "binary" ? "binary" : ""}"><code>${preview.kind === "binary" ? escapeHtml(content || "Empty file") : highlightedHtml(content || "Empty file", entry.name)}</code></pre>${preview.truncated ? '<div class="preview-warning">Preview truncated</div>' : ""}`
  }

  private focusEntry(path: string): void {
    const row = Array.from(this.root.querySelectorAll<HTMLElement>("[data-entry]"))
      .find((element) => element.dataset.entry === path)
    row?.focus()
  }

  private select(path: string, focus = false): void {
    if (this.selectedPath === path) {
      if (focus) this.focusEntry(path)
      return
    }
    this.selectedPath = path
    this.preview = null
    this.renderDirectory()
    if (focus) this.focusEntry(path)
    void this.loadPreview()
  }

  private activate(entry: FileEntry | undefined): void {
    if (!entry) return
    if (entry.type === "dir") {
      this.navigate(entry.path)
    } else {
      void this.editCurrent()
    }
  }

  private async editCurrent(): Promise<void> {
    const entry = this.current()
    if (!entry || entry.type === "dir") return
    try {
      const content = await this.context.api.get<FilePreview>(`/files/content${queryString({ machine: this.machine, path: entry.path })}`)
      const values = await openFormDialog({
        title: `Edit ${entry.name}`,
        detail: `${this.machine}:${entry.path}`,
        wide: true,
        submitLabel: "Save file",
        fields: [{ name: "content", label: "Content", value: String(content.content || ""), type: "textarea", required: false }],
      })
      if (!values) return
      await this.context.api.send("/files/write", "POST", {
        machine: this.machine,
        path: entry.path,
        content: values.content || "",
        overwrite: true,
        expected_sha256: content.sha256,
      })
      this.context.notify(`Saved ${entry.name}`, "success")
      await this.refresh()
    } catch (error) {
      this.context.notify(`Edit: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private async create(kind: "file" | "dir"): Promise<void> {
    const values = await openFormDialog({
      title: kind === "file" ? "New file" : "New folder",
      fields: [{ name: "name", label: "Name", placeholder: kind === "file" ? "notes.md" : "new-folder", required: true }],
      submitLabel: "Create",
    })
    const name = values?.name.trim()
    if (!name) return
    try {
      await this.context.api.send(`/files/${kind === "file" ? "touch" : "mkdir"}`, "POST", { machine: this.machine, path: joinPath(this.path, name) })
      this.context.notify(`Created ${name}`, "success")
      await this.refresh()
    } catch (error) {
      this.context.notify(`Create: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private async renameCurrent(): Promise<void> {
    const entry = this.current()
    if (!entry) return
    const values = await openFormDialog({ title: `Rename ${entry.name}`, fields: [{ name: "name", label: "New name", value: entry.name, required: true }], submitLabel: "Rename" })
    const name = values?.name.trim()
    if (!name || name === entry.name) return
    try {
      const destination = joinPath(this.path, name)
      await this.context.api.send("/files/rename", "POST", { machine: this.machine, path: entry.path, destination })
      this.selectedPath = destination
      this.context.notify(`Renamed to ${name}`, "success")
      await this.refresh()
    } catch (error) {
      this.context.notify(`Rename: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private async deleteCurrent(): Promise<void> {
    const entry = this.current()
    if (!entry) return
    if (!await confirmDialog(`Delete ${entry.name}?`, entry.type === "dir" ? "The directory and all contained files will be removed." : "This file will be removed.", "Delete")) return
    try {
      await this.context.api.send("/files/delete", "POST", { machine: this.machine, path: entry.path, recursive: entry.type === "dir" })
      this.selectedPath = null
      this.context.notify(`Deleted ${entry.name}`, "success")
      await this.refresh()
    } catch (error) {
      this.context.notify(`Delete: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private async paste(): Promise<void> {
    if (!this.clipboard) return
    if (this.clipboard.machine !== this.machine) {
      this.context.notify("Clipboard belongs to another machine.", "warning")
      return
    }
    const destination = joinPath(this.path, basename(this.clipboard.path))
    try {
      await this.context.api.send(`/files/${this.clipboard.mode === "copy" ? "copy" : "move"}`, "POST", { machine: this.machine, path: this.clipboard.path, destination })
      if (this.clipboard.mode === "move") this.clipboard = null
      this.context.notify(`Pasted ${basename(destination)}`, "success")
      await this.refresh()
    } catch (error) {
      this.context.notify(`Paste: ${error instanceof Error ? error.message : String(error)}`, "error")
    }
  }

  private parent(): void {
    const parent = this.payload?.parent
    if (!parent || parent === this.path) return
    this.navigate(parent)
  }

  private switchMachine(machine: string): void {
    if (!machine || machine === this.machine) return
    this.machine = machine
    this.clipboard = null
    this.renderMachines()
    this.navigate(".")
  }

  private async upload(files: FileList): Promise<void> {
    for (const file of Array.from(files)) {
      try {
        const bytes = new Uint8Array(await file.arrayBuffer())
        let binary = ""
        for (let index = 0; index < bytes.length; index += 0x8000) {
          binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000))
        }
        await this.context.api.send("/files/write", "POST", {
          machine: this.machine,
          path: joinPath(this.path, file.name),
          content: btoa(binary),
          encoding: "base64",
          overwrite: false,
        })
        this.context.notify(`Uploaded ${file.name}`, "success")
      } catch (error) {
        this.context.notify(`Upload ${file.name}: ${error instanceof Error ? error.message : String(error)}`, "error")
      }
    }
    await this.refresh()
  }

  private togglePreview(): void {
    this.previewVisible = !this.previewVisible
    this.root.querySelector(".files-layout")?.classList.toggle("preview-open", this.previewVisible)
    this.renderActions()
  }

  private onClick(event: MouseEvent): void {
    const target = event.target as HTMLElement
    const machine = target.closest<HTMLElement>("[data-machine]")?.dataset.machine
    if (machine) {
      this.switchMachine(machine)
      return
    }
    const path = target.closest<HTMLElement>("[data-path]")?.dataset.path
    if (path) {
      this.navigate(path)
      return
    }
    const entryPath = target.closest<HTMLElement>("[data-entry]")?.dataset.entry
    if (entryPath) {
      this.select(entryPath, true)
      return
    }
    const previewPath = target.closest<HTMLElement>("[data-preview-entry]")?.dataset.previewEntry
    if (previewPath) {
      const previewEntry = this.preview?.entries?.find((entry) => entry.path === previewPath)
      const current = this.current()
      if (previewEntry && current?.type === "dir") {
        this.navigate(current.path, previewEntry.path)
      }
      return
    }
    const parentPath = target.closest<HTMLElement>("[data-parent-path]")?.dataset.parentPath
    if (parentPath && parentPath !== this.path) {
      this.navigate(parentPath)
      return
    }
    const action = target.closest<HTMLElement>("[data-action]")?.dataset.action
    if (!action) return
    if (action === "parent") this.parent()
    else if (action === "new-file") void this.create("file")
    else if (action === "new-dir") void this.create("dir")
    else if (action === "upload") this.root.querySelector<HTMLInputElement>("[data-role=file-upload]")?.click()
    else if (action === "refresh") void this.refresh()
    else if (action === "home-location") this.navigate(this.machines().find((item) => item.name === this.machine)?.workdir || ".")
    else if (action === "sort-direction") {
      this.sortDirection = this.sortDirection === "asc" ? "desc" : "asc"
      this.renderDirectory()
    }
    else if (action === "toggle-preview") this.togglePreview()
    else if (action === "open") this.activate(this.current())
    else if (action === "rename") void this.renameCurrent()
    else if (action === "copy") {
      const current = this.current()
      if (current) this.clipboard = { mode: "copy", machine: this.machine, path: current.path }
      this.renderActions()
    }
    else if (action === "cut") {
      const current = this.current()
      if (current) this.clipboard = { mode: "move", machine: this.machine, path: current.path }
      this.renderActions()
    }
    else if (action === "delete") void this.deleteCurrent()
    else if (action === "paste") void this.paste()
  }

  private onDoubleClick(event: MouseEvent): void {
    const path = (event.target as HTMLElement).closest<HTMLElement>("[data-entry]")?.dataset.entry
    if (path) this.activate(this.entries().find((entry) => entry.path === path))
  }

  private onChange(event: Event): void {
    const target = event.target
    if (target instanceof HTMLSelectElement && target.dataset.role === "machine") this.switchMachine(target.value)
    if (target instanceof HTMLInputElement && target.dataset.role === "hidden") {
      this.showHidden = target.checked
      const entries = this.entries()
      if (!entries.some((entry) => entry.path === this.selectedPath)) this.selectedPath = entries[0]?.path || null
      this.renderParent()
      this.renderDirectory()
      void this.loadPreview()
    }
    if (target instanceof HTMLSelectElement && target.dataset.role === "file-sort") {
      this.sort = target.value as FileSort
      this.renderDirectory()
    }
    if (target instanceof HTMLInputElement && target.dataset.role === "file-upload" && target.files?.length) {
      void this.upload(target.files)
      target.value = ""
    }
    if (target instanceof HTMLInputElement && target.dataset.role === "path") {
      this.navigate(target.value.trim() || ".")
    }
  }

  private onInput(event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement) || target.dataset.role !== "file-search") return
    this.query = target.value
    const entries = this.entries()
    if (!entries.some((entry) => entry.path === this.selectedPath)) this.selectedPath = entries[0]?.path || null
    this.renderDirectory()
    void this.loadPreview()
  }

  private onListKeyDown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement
    const editing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement
    const mod = event.ctrlKey || event.metaKey
    if (mod && event.key.toLowerCase() === "f") {
      event.preventDefault()
      this.root.querySelector<HTMLInputElement>("[data-role=file-search]")?.focus()
      return
    }
    if (mod && event.key.toLowerCase() === "l") {
      event.preventDefault()
      const input = this.root.querySelector<HTMLInputElement>("[data-role=path]")
      input?.focus()
      input?.select()
      return
    }
    if (!editing && event.altKey && event.key === "ArrowUp") { event.preventDefault(); this.parent(); return }
    if (!editing && mod && event.key.toLowerCase() === "r") { event.preventDefault(); void this.refresh(); return }
    if (!editing && mod && event.key.toLowerCase() === "c") { const current = this.current(); if (current) this.clipboard = { mode: "copy", machine: this.machine, path: current.path }; this.renderActions(); return }
    if (!editing && mod && event.key.toLowerCase() === "x") { const current = this.current(); if (current) this.clipboard = { mode: "move", machine: this.machine, path: current.path }; this.renderActions(); return }
    if (!editing && mod && event.key.toLowerCase() === "v") { event.preventDefault(); void this.paste(); return }
    if (!editing && event.key === "F2") { event.preventDefault(); void this.renameCurrent(); return }
    if (!editing && event.key === "Delete") { event.preventDefault(); void this.deleteCurrent(); return }
    const row = target.closest<HTMLElement>("[data-entry]")
    const path = row?.dataset.entry
    if (!path) return
    const entries = this.entries()
    const index = entries.findIndex((entry) => entry.path === path)
    if (index < 0) return
    let nextIndex: number | null = null
    if (event.key === "ArrowDown") nextIndex = Math.min(entries.length - 1, index + 1)
    else if (event.key === "ArrowUp") nextIndex = Math.max(0, index - 1)
    else if (event.key === "Home") nextIndex = 0
    else if (event.key === "End") nextIndex = entries.length - 1
    else if (event.key === "Enter") {
      event.preventDefault()
      this.activate(entries[index])
      return
    } else if (event.key === " ") {
      event.preventDefault()
      this.select(path, true)
      return
    }
    if (nextIndex === null) return
    event.preventDefault()
    const next = entries[nextIndex]
    if (next) this.select(next.path, true)
  }

}

