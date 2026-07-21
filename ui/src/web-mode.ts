export const WEB_VIEWS = ["overview", "machines", "workloads", "activity", "todos"] as const
export type WebViewName = (typeof WEB_VIEWS)[number] | "console"
export type InterfaceMode = "web" | "tui"

const VIEW_SET = new Set<WebViewName>([...WEB_VIEWS, "console"])
const ALIASES: Record<string, WebViewName> = {
  web: "overview",
  dashboard: "overview",
  tui: "console",
  opentui: "console",
}

export function viewFromHash(hash: string): WebViewName | null {
  const normalized = hash.replace(/^#\/?/, "").replace(/\/$/, "").trim().toLowerCase()
  if (!normalized) return null
  const aliased = ALIASES[normalized] || normalized
  return VIEW_SET.has(aliased as WebViewName) ? aliased as WebViewName : null
}

export function hashForView(view: WebViewName): string {
  return `#/${view}`
}

export function interfaceModeForView(view: WebViewName): InterfaceMode {
  return view === "console" ? "tui" : "web"
}

export function oauthReturnView(hash: string, requestedView: WebViewName): WebViewName {
  const currentView = viewFromHash(hash)
  return currentView && interfaceModeForView(currentView) === interfaceModeForView(requestedView)
    ? currentView
    : requestedView
}
