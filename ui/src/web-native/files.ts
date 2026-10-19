import { createElement } from "react"
import { createRoot, type Root } from "react-dom/client"
import { Filemanager, Willow, type IApi, type IEntity, type IFile } from "@svar-ui/react-filemanager"
import type { FileEntry, FilesPayload, FilePreview } from "../types"
import {
  basename, confirmDialog, escapeHtml, joinPath, openFormDialog, queryString,
  type NativePageContext, type NativePageController,
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

// IDs belong to the browser tree; never use them as real machine paths.
export function fileTreeId(parent: string, name: string): string {
  return `${parent === "/" ? "" : parent}/${encodeURIComponent(name)}`
}

export function fileTreeEntries(entries: FileEntry[], parent: string, showHidden: boolean): IEntity[] {
  return entries.filter((entry) => showHidden || !entry.hidden).map((entry) => ({
    id: fileTreeId(parent, entry.name),
    name: entry.name,
    type: entry.type === "dir" ? "folder" : "file",
    size: entry.type === "dir" ? undefined : Number(entry.size || 0),
    date: entry.modified ? new Date(Number(entry.modified) * 1000) : undefined,
    lazy: entry.type === "dir",
  }))
}

const explorerFileIcon = (body: string): string =>
  `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#62748e" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`)}`
const explorerIcons = {
  folder: explorerFileIcon('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10H3z" fill="#e8f3ff" stroke="#5095d8"/>'),
  file: explorerFileIcon('<path d="M6 2h8l5 5v15H6z" fill="#f4f7fb"/><path d="M14 2v5h5"/><path d="M9 13h7M9 17h7"/>'),
  image: explorerFileIcon('<rect x="3" y="3" width="18" height="18" rx="2" fill="#edf7f0"/><circle cx="9" cy="9" r="2"/><path d="m4 19 6-6 4 4 3-3 4 4"/>'),
  archive: explorerFileIcon('<rect x="5" y="3" width="14" height="18" rx="2" fill="#fff6e9"/><path d="M12 3v12m-2-7h4m-4 4h4"/>'),
}

export function explorerIcon(file: { type?: string; name?: string; ext?: string }): string {
  if (file.type === "folder") return explorerIcons.folder
  const name = (file.name || file.ext || "").toLowerCase()
  if (/\.(jpe?g|png|gif|webp|svg)$/.test(name)) return explorerIcons.image
  if (/\.(zip|tar|gz|xz|7z|rar)$/.test(name)) return explorerIcons.archive
  return explorerIcons.file
}

export class FilesController implements NativePageController {
  private root!: HTMLElement
  private reactRoot: Root | null = null
  private api: IApi | null = null
  private machine = "local"
  private location = "."
  private selectedFolder = "/"
  private paths = new Map<string, string>([["/", "."]])
  private types = new Map<string, string>()
  private generation = 0
  private destroyed = false
  private showHidden = false
  private data: IEntity[] = []
  private busy = false

  constructor(private readonly context: NativePageContext) {}

  mount(root: HTMLElement): void {
    this.root = root
    this.machine = this.context.machines().find((m) => m.name === "local")?.name || this.context.machines()[0]?.name || "local"
    this.root.innerHTML = `<section class="native-page explorer-page">
      <header class="explorer-head">
        <div class="explorer-location"><label for="explorer-machine">Machine</label><select id="explorer-machine" data-role="machine"></select>
        <button class="native-button" data-action="up" title="Parent folder">↑</button>
        <input aria-label="Remote directory path" data-role="location" spellcheck="false" value="." title="Type an absolute or workspace-relative path"/>
        <button class="native-button" data-action="go">Go</button></div>
        <div class="explorer-head-actions"><label class="native-toggle"><input data-role="hidden" type="checkbox"/>Show hidden</label>
        <button class="native-button" data-action="refresh" title="Refresh current folder">↻ Refresh</button>
        <button class="native-button primary" data-action="upload">↑ Upload</button></div>
      </header>
      <div class="explorer-transfer-status" data-role="progress" aria-live="polite" hidden></div>
      <div class="explorer-host" data-role="explorer"></div>
      <input type="file" data-role="upload-files" multiple hidden/>
    </section>`
    this.renderMachines()
    const explorer = root.querySelector<HTMLElement>("[data-role=explorer]")!
    this.reactRoot = createRoot(explorer)
    root.addEventListener("click", this.click)
    root.addEventListener("change", this.change)
    root.addEventListener("keydown", this.keydown)
    void this.refresh()
  }

  private renderMachines(): void {
    const select = this.root.querySelector<HTMLSelectElement>("[data-role=machine]")
    if (select) select.innerHTML = this.context.machines().map((machine) =>
      `<option value="${escapeHtml(machine.name)}"${machine.name === this.machine ? " selected" : ""}>${escapeHtml(machine.name)}${machine.status === "online" ? "" : " (offline)"}</option>`
    ).join("")
  }

  private readonly click = (event: MouseEvent): void => {
    const action = (event.target as HTMLElement).closest<HTMLElement>("[data-action]")?.dataset.action
    if (action === "go") this.openLocation()
    if (action === "refresh") void this.reloadCurrent()
    if (action === "upload") this.root.querySelector<HTMLInputElement>("[data-role=upload-files]")?.click()
    if (action === "up") {
      const current = this.paths.get(this.selectedFolder) || this.location
      const parts = fileBreadcrumbRows(current)
      const parent = parts.length > 1 ? parts[parts.length - 2]!.path : "."
      this.location = parent
      void this.refresh()
    }
  }

  private readonly change = (event: Event): void => {
    const target = event.target
    if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return
    if (target.dataset.role === "machine") {
      this.machine = target.value
      this.location = "."
      void this.refresh()
    } else if (target.dataset.role === "hidden") {
      this.showHidden = (target as HTMLInputElement).checked
      this.location = this.paths.get(this.selectedFolder) || this.location
      void this.refresh()
    } else if (target.dataset.role === "upload-files") {
      const files = Array.from((target as HTMLInputElement).files || [])
      target.value = ""
      if (files.length) void this.uploadFiles(files, this.paths.get(this.selectedFolder) || this.location)
    }
  }

  private readonly keydown = (event: KeyboardEvent): void => {
    if (event.key === "Enter" && (event.target as HTMLElement).dataset.role === "location") {
      event.preventDefault()
      this.openLocation()
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "l") {
      event.preventDefault()
      this.root.querySelector<HTMLInputElement>("[data-role=location]")?.focus()
    }
  }

  private openLocation(): void {
    const location = this.root.querySelector<HTMLInputElement>("[data-role=location]")?.value.trim()
    if (!location) return
    this.location = location
    void this.refresh()
  }

  async refresh(): Promise<void> {
    const generation = ++this.generation
    const machine = this.machine
    const location = this.location
    this.api = null
    this.paths = new Map([["/", location]])
    this.types.clear()
    this.selectedFolder = "/"
    this.data = []
    this.renderMachines()
    this.root.querySelector<HTMLInputElement>("[data-role=location]")!.value = location
    const host = this.root.querySelector<HTMLElement>("[data-role=explorer]")!
    host.setAttribute("aria-busy", "true")
    try {
      const response = await this.context.api.get<FilesPayload>(`/files${queryString({ machine, path: location, include_parent: false, max_entries: 5000 })}`)
      if (generation !== this.generation || this.destroyed) return
      this.data = this.addEntries(response.entries, "/")
      if (response.truncated) this.context.notify("Directory listing reached its configured limit; additional entries may be hidden", "warning")
      this.renderExplorer(generation)
    } catch (error) {
      if (generation !== this.generation || this.destroyed) return
      this.reactRoot?.render(createElement("div", { className: "native-error" }, error instanceof Error ? error.message : String(error)))
      this.context.notify(`Files: ${error instanceof Error ? error.message : String(error)}`, "error")
    } finally {
      if (generation === this.generation && !this.destroyed) host.removeAttribute("aria-busy")
    }
  }

  private addEntries(entries: FileEntry[], parent: string): IEntity[] {
    const visible = entries.filter((entry) => this.showHidden || !entry.hidden)
    const data = fileTreeEntries(visible, parent, true)
    for (let index = 0; index < data.length; index++) {
      this.paths.set(data[index]!.id, visible[index]!.path)
      this.types.set(data[index]!.id, visible[index]!.type)
    }
    return data
  }

  private renderExplorer(generation: number): void {
    this.reactRoot?.render(createElement(Willow, { fonts: false }, createElement(Filemanager, {
      key: String(generation),
      data: this.data,
      mode: "table",
      preview: false,
      icons: explorerIcon,
      init: (api: IApi) => { if (generation === this.generation) this.api = api },
      onRequestData: ({ id }: { id: string }) => { void this.loadFolder(id, generation) },
      onSetPath: ({ id }: { id: string }) => {
        if (generation !== this.generation) return
        this.selectedFolder = id
        const path = this.paths.get(id)
        if (path) this.root.querySelector<HTMLInputElement>("[data-role=location]")!.value = path
      },
      onDownloadFile: ({ id }: { id: string }) => { void this.download(id, generation) },
      onOpenFile: ({ id }: { id: string }) => { void this.editFile(id, generation) },
      onRenameFile: ({ id, name }: { id: string; name: string }) => { void this.rename(id, name, generation) },
      onDeleteFiles: ({ ids }: { ids: string[] }) => { void this.remove(ids, generation) },
      onMoveFiles: ({ ids, target }: { ids: string[]; target: string }) => { void this.relocate(ids, target, "move", generation) },
      onCopyFiles: ({ ids, target }: { ids: string[]; target: string }) => { void this.relocate(ids, target, "copy", generation) },
      onCreateFile: ({ file, parent }: { file: IFile; parent: string }) => { void this.create(file, parent, generation) },
    })))
  }

  private async loadFolder(id: string, generation: number): Promise<void> {
    const path = this.paths.get(id)
    if (path === undefined) return
    const machine = this.machine
    try {
      const payload = await this.context.api.get<FilesPayload>(`/files${queryString({ machine, path, include_parent: false, max_entries: 5000 })}`)
      if (this.destroyed || generation !== this.generation || machine !== this.machine) return
      await this.api?.exec("provide-data", { id, data: this.addEntries(payload.entries, id) })
      if (payload.truncated) this.context.notify("Directory listing reached its configured limit; additional entries may be hidden", "warning")
    } catch (error) {
      if (generation === this.generation) this.context.notify(`Open folder: ${String(error)}`, "error")
    }
  }

  private async reloadCurrent(): Promise<void> {
    if (!this.api || this.selectedFolder === "/") { await this.refresh(); return }
    await this.loadFolder(this.selectedFolder, this.generation)
  }

  private report(error: unknown, action: string, generation: number): void {
    if (generation !== this.generation || this.destroyed) return
    this.context.notify(`${action}: ${error instanceof Error ? error.message : String(error)}`, "error")
    void this.refresh()
  }

  private async download(id: string, generation: number): Promise<void> {
    const path = this.paths.get(id)
    if (!path) return
    const machine = this.machine
    try {
      const result = await this.context.api.send<{ url: string }>("/files/download-ticket", "POST", { machine, path })
      if (this.destroyed || generation !== this.generation) return
      const anchor = document.createElement("a")
      anchor.href = result.url
      anchor.rel = "noopener"
      anchor.download = basename(path)
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (error) { this.report(error, "Download", generation) }
  }

  private async editFile(id: string, generation: number): Promise<void> {
    const path = this.paths.get(id)
    if (!path) return
    const machine = this.machine
    try {
      const content = await this.context.api.get<FilePreview>(`/files/content${queryString({ machine, path, include_parent: false, max_entries: 5000 })}`)
      if (generation !== this.generation || this.destroyed) return
      const edited = await openFormDialog({ title: `Edit ${basename(path)}`, detail: `${machine}:${path}`,
        wide: true, submitLabel: "Save", fields: [{ name: "content", label: "Content", type: "textarea", value: String(content.content || "") }],
      })
      if (!edited || edited.content === content.content) return
      await this.context.api.send("/files/write", "POST", { machine, path, content: edited.content, overwrite: true, expected_sha256: content.sha256 })
      if (generation === this.generation) { this.context.notify(`Saved ${basename(path)}`, "success"); await this.reloadCurrent() }
    } catch (error) { this.report(error, "Edit", generation) }
  }

  private async rename(id: string, name: string, generation: number): Promise<void> {
    const path = this.paths.get(id)
    if (!path) return
    const machine = this.machine
    const destination = joinPath(this.paths.get(id.slice(0, id.lastIndexOf("/")) || "/") || this.location, name)
    try {
      await this.context.api.send("/files/rename", "POST", { machine, path, destination })
      if (generation === this.generation) await this.reloadCurrent()
    } catch (error) { this.report(error, "Rename", generation) }
  }

  private async remove(ids: string[], generation: number): Promise<void> {
    const paths = ids.map((id) => ({ path: this.paths.get(id), folder: this.types.get(id) === "dir" })).filter((item): item is { path: string; folder: boolean } => !!item.path)
    if (!paths.length || !await confirmDialog(`Delete ${paths.length} item(s)?`, "Selected files and all contents of selected folders will be permanently deleted.", "Delete")) {
      if (generation === this.generation) await this.reloadCurrent()
      return
    }
    const machine = this.machine
    try {
      for (const item of paths) await this.context.api.send("/files/delete", "POST", { machine, path: item.path, recursive: item.folder })
      if (generation === this.generation) await this.reloadCurrent()
    } catch (error) { this.report(error, "Delete", generation) }
  }

  private async relocate(ids: string[], target: string, kind: "copy" | "move", generation: number): Promise<void> {
    const directory = this.paths.get(target)
    const paths = ids.map((id) => this.paths.get(id)).filter((path): path is string => !!path)
    if (!directory || !paths.length) return
    const machine = this.machine
    try {
      for (const path of paths) await this.context.api.send(`/files/${kind}`, "POST", { machine, path, destination: joinPath(directory, basename(path)) })
      if (generation === this.generation) await this.reloadCurrent()
    } catch (error) { this.report(error, kind, generation) }
  }

  private async create(file: IFile, parent: string, generation: number): Promise<void> {
    const directory = this.paths.get(parent)
    if (!directory || !file.name || file.name.includes("/") || file.name.includes("\\")) return
    if (file.file) { await this.uploadFiles([file.file], directory); return }
    const machine = this.machine
    try {
      await this.context.api.send(file.type === "folder" ? "/files/mkdir" : "/files/touch", "POST", { machine, path: joinPath(directory, file.name) })
      if (generation === this.generation) await this.reloadCurrent()
    } catch (error) { this.report(error, "Create", generation) }
  }

  private async uploadFiles(files: File[], directory: string): Promise<void> {
    if (this.busy) { this.context.notify("A file upload is already running", "warning"); return }
    const machine = this.machine
    const generation = this.generation
    const progress = this.root.querySelector<HTMLElement>("[data-role=progress]")!
    this.busy = true
    progress.hidden = false
    try {
      for (let index = 0; index < files.length; index++) {
        const file = files[index]!
        progress.textContent = `Uploading ${file.name} (${index + 1}/${files.length}, ${(file.size / 1024 / 1024).toFixed(1)} MiB)`
        const token = this.context.accessToken()
        const response = await fetch(`${this.context.apiPrefix || "/api/ui"}/files/upload${queryString({ machine, path: joinPath(directory, file.name) })}`, {
          method: "POST", body: file, headers: { "Content-Type": "application/octet-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          credentials: "same-origin", redirect: "error",
        })
        const result = await response.json() as { ok: boolean; message?: string }
        if (!response.ok || !result.ok) throw new Error(result.message || `HTTP ${response.status}`)
      }
      if (generation === this.generation) { this.context.notify(`Uploaded ${files.length} file(s)`, "success"); await this.reloadCurrent() }
    } catch (error) { this.report(error, "Upload", generation) }
    finally { progress.hidden = true; progress.textContent = ""; this.busy = false }
  }

  destroy(): void {
    this.destroyed = true
    this.generation++
    this.root.removeEventListener("click", this.click)
    this.root.removeEventListener("change", this.change)
    this.root.removeEventListener("keydown", this.keydown)
    this.reactRoot?.unmount()
    this.reactRoot = null
    this.api = null
  }
}
