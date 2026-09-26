import type { FileEntry, FilePreview, Machine } from "../types"

export type NativeViewName = "files" | "terminals" | "desktop" | "sessions" | "remotes" | "audit"
export type NoticeTone = "info" | "success" | "warning" | "error"

export interface NativeApi {
  get<T>(path: string): Promise<T>
  send<T>(path: string, method: "POST" | "PUT", body: Record<string, unknown>): Promise<T>
}

export interface NativePageContext {
  api: NativeApi
  uiPath: string
  apiPrefix?: string
  accessToken: () => string | null
  machines: () => Machine[]
  notify: (message: string, tone?: NoticeTone) => void
  refreshChrome: () => Promise<void>
}

export interface NativePageController {
  mount(root: HTMLElement): void | Promise<void>
  refresh(): void | Promise<void>
  destroy(): void
}

export const encoder = new TextEncoder()

export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;")
}

export function queryString(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ""
}

export function formatBytes(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—"
  const units = ["B", "KB", "MB", "GB", "TB"]
  let amount = Math.max(0, value)
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024
    unit += 1
  }
  return `${amount.toFixed(unit === 0 || amount >= 100 ? 0 : amount >= 10 ? 1 : 2)} ${units[unit]}`
}

export function formatAge(timestamp: unknown, explicitAge?: unknown): string {
  const age = typeof explicitAge === "number"
    ? explicitAge
    : typeof timestamp === "number"
      ? Math.max(0, Date.now() / 1000 - timestamp)
      : null
  if (age === null) return "Unknown"
  if (age < 5) return "Now"
  if (age < 60) return `${Math.floor(age)}s ago`
  if (age < 3600) return `${Math.floor(age / 60)}m ago`
  if (age < 86400) return `${Math.floor(age / 3600)}h ago`
  return `${Math.floor(age / 86400)}d ago`
}

export function formatDate(value: unknown): string {
  if (typeof value !== "number" && typeof value !== "string") return "—"
  const numeric = typeof value === "string" && /^\d+$/.test(value) ? Number(value) : value
  const date = new Date(typeof numeric === "number" && numeric < 10_000_000_000 ? numeric * 1000 : numeric)
  return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString()
}

export function joinPath(parent: string, name: string): string {
  if (parent === "/") return `/${name}`
  if (!parent || parent === ".") return name
  const separator = parent.includes("\\") && !parent.includes("/") ? "\\" : "/"
  return `${parent.replace(/[\\/]$/, "")}${separator}${name}`
}

export function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) || path || "."
}

export function fileIcon(entry: FileEntry): string {
  if (entry.type === "dir") return "▰"
  if (entry.type === "link") return "↗"
  const lower = entry.name.toLowerCase()
  if (/\.(png|jpe?g|gif|webp|svg)$/.test(lower)) return "▧"
  if (/\.(zip|tar|gz|xz|7z)$/.test(lower)) return "◆"
  if (/\.(md|txt|rst|log)$/.test(lower)) return "≡"
  if (/\.(ts|tsx|js|jsx|py|rs|go|c|cpp|java|sh)$/.test(lower)) return "⌁"
  return "·"
}

export function statusClass(value: string): string {
  const normalized = value.toLowerCase()
  if (["online", "success", "completed", "healthy"].includes(normalized)) return "success"
  if (["failed", "error", "critical", "offline"].includes(normalized)) return "error"
  if (["running", "starting", "attention", "warning", "unpaired"].includes(normalized)) return "warning"
  return "neutral"
}

export function button(label: string, action: string, options: { icon?: string; primary?: boolean; danger?: boolean; disabled?: boolean; title?: string } = {}): string {
  const classes = ["native-button"]
  if (options.primary) classes.push("primary")
  if (options.danger) classes.push("danger")
  return `<button class="${classes.join(" ")}" type="button" data-action="${escapeHtml(action)}"${options.disabled ? " disabled" : ""}${options.title ? ` title="${escapeHtml(options.title)}"` : ""}>${options.icon ? `<span aria-hidden="true">${options.icon}</span>` : ""}${escapeHtml(label)}</button>`
}

export function highlightedHtml(text: string, filename = ""): string {
  const escaped = escapeHtml(text)
  const lower = filename.toLowerCase()
  const jsonLike = /\.(json|jsonl)$/.test(lower) || /^[\s]*[\[{]/.test(text)
  if (jsonLike) {
    return escaped
      .replace(/(&quot;(?:\\.|[^&])*?&quot;)(\s*:)?/g, (_all, quoted: string, colon: string | undefined) => `<span class="syntax-${colon ? "key" : "string"}">${quoted}</span>${colon || ""}`)
      .replace(/\b(-?\d+(?:\.\d+)?)\b/g, '<span class="syntax-number">$1</span>')
      .replace(/\b(true|false|null)\b/g, '<span class="syntax-literal">$1</span>')
  }
  if (/\.(md|markdown|rst)$/.test(lower)) {
    return escaped
      .replace(/^(#{1,6}\s+.*)$/gm, '<span class="syntax-heading">$1</span>')
      .replace(/(`[^`\n]+`)/g, '<span class="syntax-string">$1</span>')
  }
  if (/\.(ts|tsx|js|jsx|py|rs|go|c|cpp|java|sh|bash|zsh)$/.test(lower)) {
    const tokens = /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|#[^\n]*|\/\/[^\n]*|\b(?:async|await|break|case|catch|class|const|continue|def|else|export|extends|false|finally|for|from|function|if|import|in|interface|let|match|new|null|return|struct|throw|true|try|type|use|var|while|yield)\b)/g
    let output = ""
    let offset = 0
    for (const match of text.matchAll(tokens)) {
      const index = match.index ?? 0
      const token = match[0]
      output += escapeHtml(text.slice(offset, index))
      const className = token.startsWith("#") || token.startsWith("//")
        ? "syntax-comment"
        : token.startsWith('"') || token.startsWith("'") || token.startsWith("`")
          ? "syntax-string"
          : "syntax-keyword"
      output += `<span class="${className}">${escapeHtml(token)}</span>`
      offset = index + token.length
    }
    return output + escapeHtml(text.slice(offset))
  }
  return escaped
}

export function rgbaCanvas(preview: FilePreview): HTMLCanvasElement | null {
  if (!preview.rgba || !preview.width || !preview.height) return null
  try {
    const binary = atob(preview.rgba)
    const bytes = new Uint8ClampedArray(binary.length)
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
    const canvas = document.createElement("canvas")
    canvas.width = preview.width
    canvas.height = preview.height
    const context = canvas.getContext("2d")
    if (!context) return null
    context.putImageData(new ImageData(bytes, preview.width, preview.height), 0, 0)
    canvas.className = "rgba-preview"
    return canvas
  } catch {
    return null
  }
}

export async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value)
    return true
  } catch {
    const textarea = document.createElement("textarea")
    textarea.value = value
    textarea.style.position = "fixed"
    textarea.style.opacity = "0"
    document.body.appendChild(textarea)
    textarea.select()
    const copied = document.execCommand("copy")
    textarea.remove()
    return copied
  }
}

type DialogField = {
  name: string
  label: string
  value?: string
  placeholder?: string
  type?: "text" | "number" | "textarea"
  required?: boolean
  help?: string
}

type DialogOptions = {
  title: string
  detail?: string
  fields: DialogField[]
  submitLabel?: string
  danger?: boolean
  wide?: boolean
}

export async function openFormDialog(options: DialogOptions): Promise<Record<string, string> | null> {
  return new Promise((resolve) => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overlay = document.createElement("div")
    overlay.className = "native-dialog-overlay"
    const fields = options.fields.map((field) => {
      const control = field.type === "textarea"
        ? `<textarea name="${escapeHtml(field.name)}" placeholder="${escapeHtml(field.placeholder || "")}"${field.required ? " required" : ""}>${escapeHtml(field.value || "")}</textarea>`
        : `<input name="${escapeHtml(field.name)}" type="${field.type === "number" ? "number" : "text"}" value="${escapeHtml(field.value || "")}" placeholder="${escapeHtml(field.placeholder || "")}"${field.required ? " required" : ""}/>`
      return `<label class="native-field"><span>${escapeHtml(field.label)}</span>${control}${field.help ? `<small>${escapeHtml(field.help)}</small>` : ""}</label>`
    }).join("")
    overlay.innerHTML = `<form class="native-dialog${options.wide ? " wide" : ""}" role="dialog" aria-modal="true" tabindex="-1">
      <header><div><h2>${escapeHtml(options.title)}</h2>${options.detail ? `<p>${escapeHtml(options.detail)}</p>` : ""}</div><button type="button" data-dialog-cancel aria-label="Close">×</button></header>
      <div class="native-dialog-body">${fields}</div>
      <footer><button class="native-button" type="button" data-dialog-cancel>Cancel</button><button class="native-button ${options.danger ? "danger" : "primary"}" type="submit">${escapeHtml(options.submitLabel || "Save")}</button></footer>
    </form>`
    document.body.appendChild(overlay)
    const form = overlay.querySelector<HTMLFormElement>("form")!
    let closed = false
    const close = (result: Record<string, string> | null) => {
      if (closed) return
      closed = true
      overlay.remove()
      if (previousFocus?.isConnected) previousFocus.focus()
      resolve(result)
    }
    overlay.querySelectorAll<HTMLElement>("[data-dialog-cancel]").forEach((element) => element.addEventListener("click", () => close(null)))
    overlay.addEventListener("mousedown", (event) => {
      if (event.target === overlay) close(null)
    })
    overlay.addEventListener("keydown", (event) => {
      event.stopPropagation()
      if (event.key === "Escape") {
        event.preventDefault()
        close(null)
        return
      }
      if (event.key !== "Tab") return
      const focusable = Array.from(overlay.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'))
        .filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true")
      if (!focusable.length) {
        event.preventDefault()
        form.focus()
        return
      }
      const first = focusable[0]!
      const last = focusable.at(-1)!
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    })
    form.addEventListener("submit", (event) => {
      event.preventDefault()
      const data = new FormData(form)
      close(Object.fromEntries([...data.entries()].map(([key, value]) => [key, String(value)])))
    })
    window.requestAnimationFrame(() => {
      const firstField = form.querySelector<HTMLElement>("input,textarea,select")
      const submit = form.querySelector<HTMLButtonElement>('button[type="submit"]')
      const focusTarget = firstField || submit || form
      focusTarget.focus()
    })
  })
}

export async function confirmDialog(title: string, detail: string, confirmLabel = "Confirm"): Promise<boolean> {
  const result = await openFormDialog({ title, detail, fields: [], submitLabel: confirmLabel, danger: true })
  return result !== null
}

export abstract class BaseController implements NativePageController {
  protected root!: HTMLElement
  protected readonly listeners: Array<() => void> = []
  protected readonly timers: number[] = []
  protected readonly aborters = new Set<AbortController>()
  protected destroyed = false

  constructor(protected readonly context: NativePageContext) {}

  abstract mount(root: HTMLElement): void | Promise<void>
  abstract refresh(): void | Promise<void>

  protected listen<K extends keyof HTMLElementEventMap>(target: HTMLElement | Document | Window, type: K, listener: (event: HTMLElementEventMap[K]) => void, options?: AddEventListenerOptions): void {
    target.addEventListener(type, listener as EventListener, options)
    this.listeners.push(() => target.removeEventListener(type, listener as EventListener, options))
  }

  protected every(callback: () => void, milliseconds: number): void {
    this.timers.push(window.setInterval(callback, milliseconds))
  }

  protected controller(): AbortController {
    const controller = new AbortController()
    this.aborters.add(controller)
    controller.signal.addEventListener("abort", () => this.aborters.delete(controller), { once: true })
    return controller
  }

  destroy(): void {
    this.destroyed = true
    this.listeners.splice(0).forEach((remove) => remove())
    this.timers.splice(0).forEach((timer) => window.clearInterval(timer))
    this.aborters.forEach((controller) => controller.abort())
    this.aborters.clear()
  }
}

