import { createCliRenderer } from "@opentui/core"
import { createRoot, useKeyboard, useRenderer, useTerminalDimensions } from "@opentui/react"
import { useCallback, useEffect, useRef, useState } from "react"
import { api, formatError } from "./api"
import { AuditScreen } from "./audit-screen"
import { Modal, SCREENS, TopNav } from "./components"
import { FilesScreen } from "./files-screen"
import { RemotesScreen } from "./remotes-screen"
import { TerminalsScreen } from "./terminals-screen"
import { theme } from "./theme"
import { TodosScreen } from "./todos-screen"
import type { BootstrapPayload, Machine, ScreenName } from "./types"

function Help({ close }: { close: () => void }) {
  useKeyboard((key) => {
    if (key.name === "escape" || key.name === "f1" || key.name === "return") close()
  })
  return (
    <Modal title="Keyboard guide" width={82} height={22}>
      <text fg={theme.cyan} attributes={1} content="Global navigation" />
      <text fg={theme.muted} content="Alt+1…5  switch top-level screen (F2…F6 also work)" />
      <text fg={theme.muted} content="F7        refresh machine list" />
      <text fg={theme.muted} content="Ctrl+Q    quit the TUI" />
      <text fg={theme.muted} content="F1        show this guide" />
      <text fg={theme.borderBright} content="\nScreen conventions" />
      <text fg={theme.muted} content="j/k or arrows move selection · Enter activates · Esc closes dialogs" />
      <text fg={theme.muted} content="[ / ] switches machines in Files and Terminals" />
      <text fg={theme.muted} content="The footer on every screen lists its contextual commands." />
      <text fg={theme.borderBright} content="\nAudit policy" />
      <text fg={theme.muted} content="Audit contains MCP-originated operations. Actions typed by a human in this TUI or the WebUI are intentionally excluded." />
      <box style={{ flexGrow: 1 }} />
      <text fg={theme.faint} content="Esc / Enter close" />
    </Modal>
  )
}

function StatusLine({ status, bootstrap }: { status: string; bootstrap: BootstrapPayload | null }) {
  const online = bootstrap?.machines.machines.filter((machine) => machine.status === "online").length || 0
  return (
    <box
      style={{
        height: 2,
        flexDirection: "row",
        alignItems: "center",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: theme.bg,
      }}
    >
      <text fg={theme.green} content="● " />
      <text fg={theme.muted} content={`${online} online`} />
      <text fg={theme.faint} content="  │  " />
      <text fg={theme.muted} content={status} />
      <box style={{ flexGrow: 1 }} />
      <text fg={theme.faint} content={bootstrap?.features.yazi_available ? "Yazi available" : "Yazi UX mode"} />
      <text fg={theme.faint} content="  │  " />
      <text fg={theme.cyan} content="local-shell-mcp" />
    </box>
  )
}

function App() {
  const renderer = useRenderer()
  const { width, height } = useTerminalDimensions()
  const [screen, setScreen] = useState<ScreenName>("Files")
  const [bootstrap, setBootstrap] = useState<BootstrapPayload | null>(null)
  const [machine, setMachine] = useState("local")
  const [status, setStatus] = useState("Connecting to local-shell-mcp…")
  const [help, setHelp] = useState(false)
  const [terminalRawMode, setTerminalRawMode] = useState(false)
  const bootstrapRequest = useRef(0)

  const loadBootstrap = useCallback(async () => {
    const requestId = ++bootstrapRequest.current
    try {
      const payload = await api.bootstrap()
      if (requestId !== bootstrapRequest.current) return
      setBootstrap(payload)
      setMachine((current) =>
        payload.machines.machines.some((item) => item.name === current) ? current : "local",
      )
      setStatus(`Ready · ${payload.machines.counts.total || payload.machines.machines.length} machines`)
    } catch (error) {
      if (requestId === bootstrapRequest.current) {
        setStatus(`Connection failed: ${formatError(error)}`)
      }
    }
  }, [])

  useEffect(() => {
    void loadBootstrap()
    const timer = setInterval(() => void loadBootstrap(), 8_000)
    return () => {
      bootstrapRequest.current += 1
      clearInterval(timer)
    }
  }, [loadBootstrap])

  useKeyboard((key) => {
    if (help || terminalRawMode) return
    if (key.ctrl && key.name === "q") renderer.destroy()
    else if (key.name === "f1") setHelp(true)
    else if (key.option && /^[1-5]$/.test(key.name)) setScreen(SCREENS[Number(key.name) - 1]!)
    else if (/^f[2-6]$/.test(key.name)) setScreen(SCREENS[Number(key.name.slice(1)) - 2]!)
    else if (key.name === "f7") void loadBootstrap()
  })

  const machines: Machine[] = bootstrap?.machines.machines || [
    { name: "local", status: "online", capabilities: ["files", "terminals"] },
  ]
  const contentHeight = Math.max(12, height - 5)

  let content
  if (screen === "Files") {
    content = (
      <FilesScreen
        machines={machines}
        machine={machine}
        onMachine={setMachine}
        width={width}
        height={contentHeight}
        setStatus={setStatus}
      />
    )
  } else if (screen === "Terminals") {
    content = (
      <TerminalsScreen
        machines={machines}
        machine={machine}
        onMachine={setMachine}
        width={width}
        height={contentHeight}
        setStatus={setStatus}
        onRawModeChange={setTerminalRawMode}
      />
    )
  } else if (screen === "Todos") {
    content = <TodosScreen width={width} height={contentHeight} setStatus={setStatus} />
  } else if (screen === "Audit") {
    content = <AuditScreen machines={machines} width={width} height={contentHeight} setStatus={setStatus} />
  } else {
    content = <RemotesScreen width={width} height={contentHeight} setStatus={setStatus} />
  }

  return (
    <box style={{ width: "100%", height: "100%", flexDirection: "column", backgroundColor: theme.bg, padding: 1 }}>
      <TopNav
        active={screen}
        width={width}
        onSelect={(next) => {
          if (!terminalRawMode) setScreen(next)
        }}
      />
      <box style={{ flexGrow: 1, marginTop: 1 }}>{content}</box>
      <StatusLine status={status} bootstrap={bootstrap} />
      {help && <Help close={() => setHelp(false)} />}
    </box>
  )
}

if (process.argv.includes("--version") || process.argv.includes("-V")) {
  console.log("local-shell-mcp OpenTUI")
  process.exit(0)
}
if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log("Usage: local-shell-mcp-tui [--help] [--version]")
  process.exit(0)
}

const renderer = await createCliRenderer({
  exitOnCtrlC: false,
  targetFps: 30,
})
createRoot(renderer).render(<App />)
