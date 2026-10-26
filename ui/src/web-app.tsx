/** @jsxImportSource react */
import { useLayoutEffect, useRef } from "react"
import { createRoot, type Root } from "react-dom/client"
import { flushSync } from "react-dom"
import { Button, MainTable, Spinner } from "@canonical/react-components"
import { activeJobCount } from "./web-data"
import type { NativePageController } from "./web-native/common"

const destinations = [
  ["overview", "Overview", "≡"], ["files", "Files", "▱"],
  ["terminals", "Terminals", ">_"], ["desktop", "Desktop", "▣"],
  ["sessions", "Sessions", "▤"], ["remotes", "Remotes", "▥"], ["audit", "Audit", "☷"],
] as const

function NavigationIcon({ view }: { view: string }) {
  const paths: Record<string, string> = {
    overview: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
    files: "M3 7V5h6l3 3h9v12H3z",
    terminals: "m7 8 4 4-4 4M14 16h4M3 4h18v16H3z",
    desktop: "M3 4h18v13H3zM8 21h8M12 17v4",
    sessions: "M6 3h12v18H6zM9 7h6M9 11h6M9 15h4",
    remotes: "M3 3h18v7H3zM3 14h18v7H3zM7 6.5h.01M7 17.5h.01M11 6.5h6M11 17.5h6",
    audit: "M5 3h14v18H5zM8 7h8M8 11h8M8 15h5",
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={paths[view] || paths.terminals} /></svg>
}

export function ApplicationShell() {
  return <>
    <a className="skip-link" href="#view-root">Skip to content</a>
    <section className="auth-gate" id="auth-gate" hidden>
      <div className="auth-card">
        <div className="login-brand">local-shell-mcp</div>
        <h1>Sign in</h1><p>Connect to your controller.</p>
        <div className="auth-actions">
          <Button id="login-web-button" appearance="positive">Open Web UI</Button>
          <Button id="login-button">Open TUI</Button>
        </div><small id="gate-detail" role="status">Checking access…</small>
      </div>
    </section>
    <div className="app-shell" id="app-shell" hidden>
      <aside className="sidebar" id="navigation">
        <a href="#overview" className="brand-block"><span className="brand-symbol" aria-hidden="true"><NavigationIcon view="terminals" /></span><strong>local-shell-mcp</strong></a>
        <div className="interface-switch" role="group" aria-label="Interface mode">
          <Button className="active" data-interface-mode="web" aria-pressed="true">Web UI</Button>
          <Button data-interface-mode="tui" aria-pressed="false">TUI</Button>
        </div>
        <div className="navigation-label">Workspace</div>
        <nav className="primary-nav p-side-navigation" aria-label="Primary navigation">
          {destinations.map(([view, label]) => <button key={view} className={`nav-item${view === "overview" ? " active" : ""}`} type="button" data-view={view} aria-label={label}>
            <span className="nav-icon" aria-hidden="true"><NavigationIcon view={view} /></span><span>{label}</span>
            {view === "remotes" && <span className="nav-badge" id="machine-nav-count">—</span>}
            {view === "terminals" && <span className="nav-badge" id="workload-nav-count">—</span>}
          </button>)}
        </nav>
        <div className="sidebar-spacer" />
        <div className="controller-card">
          <div className="controller-row"><span className="status-orb" id="controller-orb" /><strong id="controller-status">Connecting</strong></div>
          <span id="controller-uptime">Loading uptime…</span>
          <div className="controller-meta"><span id="controller-version">—</span><span id="controller-origin">—</span></div>
        </div>
      </aside>
      <button className="navigation-scrim" type="button" aria-label="Close navigation" hidden />
      <main className="main-content" id="web-view">
        <header className="topbar">
          <Button className="navigation-toggle" aria-label="Open navigation" aria-controls="navigation" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg></Button>
          <div className="page-heading"><span className="page-context">Controller</span><h1 id="page-title">Overview</h1></div>
          <div className="topbar-actions">
            <span className="live-pill" id="live-pill"><i /><span id="updated-at">Waiting for data</span></span>
            <Button id="refresh-button">Refresh</Button><Button id="open-console-button">Open TUI</Button>
          </div>
        </header>
        <div id="view-root" tabIndex={-1}><Spinner text="Loading control plane…" /></div>
        <footer className="page-footer"><span id="footer-version">local-shell-mcp</span><span id="footer-health">Connecting</span><span id="footer-checked">Not checked yet</span><a href={(typeof window === "undefined" ? "/ui" : window.__LSM_UI_CONFIG__?.uiPath || "/ui") + "/assets/third-party-notices.txt"} target="_blank" rel="noreferrer">Licenses</a></footer>
      </main>
      <main className="console-content shell" id="console-view" hidden>
        <div className="console-wallpaper" aria-hidden="true" />
        <header className="console-header">
          <Button className="navigation-toggle" aria-label="Open navigation" aria-controls="navigation" aria-expanded="false"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg></Button>
          <h1>TUI</h1><div className="console-actions">
            <div className="connection" id="connection-state"><span /><strong>Not started</strong></div>
            <Button id="reconnect-button">Reconnect</Button><Button id="fullscreen-button">Fullscreen</Button>
          </div>
        </header>
        <section className="terminal-card" aria-label="local-shell-mcp terminal user interface">
          <div id="terminal" />
          <nav className="touchbar" id="touchbar" aria-label="Terminal shortcut keys">
            {[["escape","Esc"],["tab","Tab"],["left","←"],["up","↑"],["down","↓"],["right","→"],["enter","Enter"],["help","F1"]].map(([key,label]) => <button key={key} type="button" data-key={key}>{label}</button>)}
            <button id="keyboard-button" type="button" data-key="keyboard" aria-label="Show keyboard" aria-pressed="false">KB</button>
          </nav>
          <footer className="terminal-footer"><span>OpenTUI</span><button className="terminal-copy-button" id="terminal-copy-button" type="button" hidden>Copy invite command</button><span id="terminal-size">—</span></footer>
        </section>
      </main>
    </div>
  </>
}

export function mountApplication() {
  const host = document.getElementById("application")!
  flushSync(() => createRoot(host).render(<ApplicationShell />))
  const toggles = document.querySelectorAll<HTMLButtonElement>(".navigation-toggle")
  const scrim = document.querySelector<HTMLButtonElement>(".navigation-scrim")!
  let opener: HTMLButtonElement | null = null
  const restoreFocus = () => {
    const target = opener?.getClientRects().length ? opener : Array.from(toggles).find(button => button.getClientRects().length)
    target?.focus()
  }
  const setOpen = (open: boolean) => {
    document.body.classList.toggle("navigation-open", open)
    toggles.forEach(button => button.setAttribute("aria-expanded", String(open)))
    scrim.hidden = !open
    if (open) (document.querySelector<HTMLElement>("#navigation .nav-item.active") || document.querySelector<HTMLElement>("#navigation .nav-item"))?.focus()
  }
  toggles.forEach(button => button.addEventListener("click", () => {
    opener = button
    setOpen(!document.body.classList.contains("navigation-open"))
  }))
  scrim.addEventListener("click", () => { setOpen(false); restoreFocus() })
  document.querySelector(".primary-nav")!.addEventListener("click", () => setOpen(false))
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && document.body.classList.contains("navigation-open")) {
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      restoreFocus()
    }
    if (event.key !== "Tab" || !document.body.classList.contains("navigation-open")) return
    const items = Array.from(document.querySelectorAll<HTMLElement>("#navigation a, #navigation button"))
    const first = items[0], last = items.at(-1)
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  })
}

function ControllerPage({ controller }: { controller: NativePageController }) {
  const host = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    void controller.mount(host.current!)
    return () => controller.destroy()
  }, [controller])
  return <div className="controller-page" ref={host} />
}

let pageRoot: Root | null = null
export function unmountReactPage() { pageRoot?.unmount(); pageRoot = null }
export function mountControllerPage(host: HTMLElement, controller: NativePageController) {
  unmountReactPage()
  pageRoot = createRoot(host)
  flushSync(() => pageRoot!.render(<ControllerPage controller={controller} />))
}

type OverviewData = {
  health?: string
  system?: Record<string, unknown>
  machines?: { machines?: Array<{ name?: string; status?: string; workdir?: string; info?: Record<string, unknown> }> }
  job_counts?: Record<string, number>
  session_count?: number
  audit_total_24h?: number
  alerts?: Array<{ title?: string; detail?: string; severity?: string }>
  activity?: Array<{ title?: string; node?: string; timestamp?: number }>
  jobs?: Array<Record<string, unknown>>
  sessions?: Array<Record<string, unknown>>
}
function percent(value: unknown) { return typeof value === "number" ? `${value.toFixed(1)}%` : "—" }

export function Overview({ data, navigate }: { data: OverviewData; navigate: (view: string) => void }) {
  const machines = data.machines?.machines || []
  const system = data.system || {}
  const metrics = [
    ["Machines", machines.length, "remotes"], ["Active jobs", activeJobCount(data), "terminals"],
    ["Sessions", data.session_count ?? 0, "sessions"], ["MCP calls · 24h", data.audit_total_24h ?? 0, "audit"],
  ] as const
  return <div className="overview-page">
    <div className={`health-banner ${data.health === "healthy" ? "healthy" : "attention"}`} role="status">
      <span className="status-orb" /><strong>{data.health === "healthy" ? "Controller online" : "Controller needs attention"}</strong>
      <Button appearance="link" onClick={() => navigate("activity")}>View alerts ({data.alerts?.length ?? 0})</Button>
    </div>
    <section className="overview-metrics" aria-label="Workspace summary">
      {metrics.map(([label,value,view]) => <button key={label} className="summary-metric" onClick={() => navigate(view)}><span>{label}</span><strong>{value}</strong><span aria-hidden="true">→</span></button>)}
    </section>
    <section className="overview-resources" aria-label="Controller resources">
      {([["CPU",system.cpu_percent],["Memory",system.memory_percent],["Workspace disk",system.disk_percent]] as const).map(([label,value]) => <div className="resource-meter" key={label}><div><span>{label}</span><strong>{percent(value)}</strong></div><progress max={100} value={typeof value === "number" ? value : 0} aria-label={label} />{typeof value !== "number" && <small>Unavailable</small>}</div>)}
    </section>
    <section className="overview-section"><header><h2>Machines</h2><Button onClick={() => navigate("remotes")}>Manage remotes</Button></header>
      <MainTable sortable responsive headers={[{content:"Name",sortKey:"name"},{content:"Status",sortKey:"status"},{content:"Resources"},{content:"Working directory"}]} emptyStateMsg="No machines connected."
        rows={machines.map(machine => ({key: machine.name, sortData: {name:machine.name,status:machine.status}, columns:[
          {content:<Button appearance="link" onClick={() => navigate("remotes")}>{machine.name}</Button>},
          {content:<span className={`status-chip ${machine.status === "online" ? "success" : "neutral"}`}>{machine.status || "Unknown"}</span>},
          {content:<div className="machine-resources"><span>CPU {percent(machine.info?.local ? system.cpu_percent : machine.info?.cpu_percent)}</span><span>MEM {percent(machine.info?.local ? system.memory_percent : machine.info?.memory_percent)}</span></div>},
          {content:<code title={machine.workdir}>{machine.workdir || "—"}</code>},
        ]}))} />
    </section>
    <div className="overview-bottom">
      <section className="overview-section"><header><h2>Needs attention</h2><Button appearance="link" onClick={() => navigate("activity")}>View all</Button></header>
        {data.alerts?.length ? data.alerts.map((alert,index) => <article className="overview-alert" key={index}><strong>{alert.title}</strong><p>{alert.detail}</p></article>) : <p className="overview-empty">No active alerts.</p>}
      </section>
      <section className="overview-section"><header><h2>Recent activity</h2><Button appearance="link" onClick={() => navigate("audit")}>Open audit</Button></header>
        {data.activity?.length ? data.activity.slice(0,6).map((entry,index) => <article className="overview-event" key={index}><span>{entry.title}</span><small>{entry.node}</small></article>) : <p className="overview-empty">No recent activity.</p>}
      </section>
    </div>
  </div>
}
export function mountOverview(host: HTMLElement, data: OverviewData, navigate: (view: string) => void) {
  if (!pageRoot) pageRoot = createRoot(host)
  flushSync(() => pageRoot!.render(<Overview data={data} navigate={navigate} />))
}

export function mountDataPage(host: HTMLElement, kind: "workloads" | "activity", data: OverviewData, navigate: (view: string) => void) {
  if (!pageRoot) pageRoot = createRoot(host)
  const workloads = [
    ...(data.jobs || []).map(item => ({item, kind: "Job"})),
    ...(data.sessions || []).map(item => ({item, kind: "Session"})),
  ]
  flushSync(() => pageRoot!.render(kind === "workloads" ? <section className="overview-section">
    <header><h2>Active workloads</h2><Button onClick={() => navigate("terminals")}>Open terminals</Button></header>
    <MainTable responsive sortable emptyStateMsg="No active jobs or persistent sessions."
      headers={[{content:"Name",sortKey:"name"},{content:"Type"},{content:"Machine"},{content:"Status"},{content:"Command / directory"}]}
      rows={workloads.map(({item,kind},index) => ({key:index,sortData:{name:String(item.name || item.session_id || item.job_id || "")},columns:[
        {content:String(item.name || item.session_id || item.job_id || "Unnamed")}, {content:kind},
        {content:String(item.machine || item.node || "local")},{content:String(item.status || "Unknown")},
        {content:<code>{String(item.command || item.cwd || item.workdir || "—")}</code>},
      ]}))} />
  </section> : <div className="page-stack">
    <section className="overview-section"><header><h2>Alerts</h2></header>
      {data.alerts?.length ? data.alerts.map((alert,index) => <article className="overview-alert" key={index}><strong>{alert.title}</strong><p>{alert.detail}</p></article>) : <p className="overview-empty">No active alerts.</p>}
    </section>
    <section className="overview-section"><header><h2>Recent MCP activity</h2><Button onClick={() => navigate("audit")}>Open audit</Button></header>
      <MainTable responsive headers={[{content:"Activity"},{content:"Machine"},{content:"Time"}]} emptyStateMsg="No recent activity."
        rows={(data.activity || []).map((entry,index) => ({key:index,columns:[{content:entry.title},{content:entry.node},{content:entry.timestamp ? new Date(entry.timestamp * 1000).toLocaleString() : "—"}]}))} />
    </section>
  </div>))
}
