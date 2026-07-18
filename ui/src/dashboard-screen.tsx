import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, Panel, formatAge, formatBytes } from "./components"
import {
  areaChart,
  clampPercent,
  dashboardLayout,
  formatDuration,
  formatRate,
  sparkline,
  trendRangeLabel,
  truncate,
  type TrendSample,
} from "./dashboard-utils"
import { screenTheme, theme } from "./theme"
import type {
  DashboardActivity,
  DashboardAlert,
  DashboardJob,
  DashboardPayload,
  DashboardSystem,
  Machine,
  TerminalSession,
} from "./types"

const colors = screenTheme.Dashboard
const ACTIVE_JOB_STATUSES = new Set(["starting", "running", "stopping", "retrying"])

function versionFrom(payload: DashboardPayload | null): string {
  return String(payload?.version.version || payload?.version.package_version || "—")
}

function machineVersion(machine: Machine): string {
  const info = machine.info || {}
  const direct = info.version || info.lsm_version
  if (direct) return String(direct)
  const nested = info.local_shell_mcp
  if (nested && typeof nested === "object" && "version" in nested) {
    return String((nested as Record<string, unknown>).version || "—")
  }
  return machine.name === "local" ? "controller" : "—"
}

function healthColor(health: string): string {
  if (health === "critical") return theme.red
  if (health === "attention") return theme.yellow
  return theme.green
}

function severityColor(severity: string): string {
  if (severity === "critical") return theme.red
  if (severity === "warning") return theme.yellow
  return theme.blue
}

function statusColor(status?: string): string {
  if (status === "running" || status === "online") return theme.green
  if (status === "starting" || status === "retrying" || status === "stopping") return theme.yellow
  if (status === "failed" || status === "lost" || status === "offline") return theme.red
  return theme.blue
}

function activityColor(kind: string): string {
  if (kind === "failed") return theme.red
  if (kind === "running") return theme.yellow
  return theme.green
}

function summaryValue(value: number | undefined): string {
  return String(value || 0)
}

function MetricCard({
  title,
  value,
  detail,
  color,
}: {
  title: string
  value: string
  detail: string
  color: string
}) {
  return (
    <Panel title={title} style={{ flexGrow: 1, minWidth: 11, justifyContent: "center", paddingLeft: 1 }}>
      <text fg={color} attributes={1} content={value} />
      <text fg={theme.faint} content={detail} />
    </Panel>
  )
}

function SummaryStrip({ payload, width }: { payload: DashboardPayload; width: number }) {
  const online = payload.machines.counts.online || 0
  const total = payload.machines.counts.total || payload.machines.machines.length
  const running = payload.jobs.filter((job) => ACTIVE_JOB_STATUSES.has(job.status || "")).length
  const full = width >= 145
  return (
    <box style={{ height: width < 82 ? 4 : 5, flexDirection: "row", gap: 1 }}>
      <Panel
        title="System health"
        active
        accent={healthColor(payload.health)}
        activeBackground={colors.panel}
        style={{ flexGrow: full ? 1.45 : 1, minWidth: 16, justifyContent: "center", paddingLeft: 1 }}
      >
        <text fg={healthColor(payload.health)} attributes={1} content={`● ${payload.health.toUpperCase()}`} />
        <text fg={theme.faint} content={payload.alerts.length ? `${payload.alerts.length} item(s) need attention` : "All observed systems nominal"} />
      </Panel>
      <MetricCard title="Nodes" value={`${online}/${total}`} detail="online" color={theme.green} />
      <MetricCard title="Jobs" value={summaryValue(running)} detail="active" color={theme.blue} />
      {width >= 92 && <MetricCard title="Sessions" value={summaryValue(payload.session_count)} detail="persistent" color={theme.magenta} />}
      {width >= 118 && <MetricCard title="Todos" value={summaryValue(payload.todo_counts.open)} detail="open" color={theme.orange} />}
      {full && <MetricCard title="Audit" value={summaryValue(payload.audit_total_24h)} detail="calls · 24h" color={theme.cyan} />}
      {full && <MetricCard title="Uptime" value={formatDuration(payload.system.uptime_s)} detail="controller" color={theme.muted} />}
    </box>
  )
}

function ResourceBars({ system, width }: { system: DashboardSystem; width: number }) {
  if (width < 44) {
    return (
      <text
        fg={theme.muted}
        content={`CPU ${Math.round(system.cpu_percent || 0)}%  MEM ${Math.round(system.memory_percent || 0)}%  DISK ${Math.round(system.disk_percent || 0)}%`}
      />
    )
  }
  const barWidth = Math.max(6, Math.min(18, width - 15))
  const bar = (value?: number | null) => {
    const percent = clampPercent(value)
    const filled = Math.round((percent / 100) * barWidth)
    return `${"█".repeat(filled)}${"░".repeat(Math.max(0, barWidth - filled))}`
  }
  return (
    <box style={{ flexDirection: "column", marginTop: 1 }}>
      <box style={{ flexDirection: "row" }}>
        <text fg={theme.faint} content="CPU   " />
        <text fg={theme.green} content={bar(system.cpu_percent)} />
        <text fg={theme.muted} content={` ${Math.round(system.cpu_percent || 0)}%`} />
      </box>
      <box style={{ flexDirection: "row" }}>
        <text fg={theme.faint} content="MEM   " />
        <text fg={theme.blue} content={bar(system.memory_percent)} />
        <text fg={theme.muted} content={` ${Math.round(system.memory_percent || 0)}%`} />
      </box>
      <box style={{ flexDirection: "row" }}>
        <text fg={theme.faint} content="DISK  " />
        <text fg={(system.disk_percent || 0) >= 85 ? theme.yellow : theme.magenta} content={bar(system.disk_percent)} />
        <text fg={theme.muted} content={` ${Math.round(system.disk_percent || 0)}%`} />
      </box>
    </box>
  )
}

function NodeFleet({ payload, width, rows }: { payload: DashboardPayload; width: number; rows: number }) {
  const machines = payload.machines.machines.slice(0, Math.max(2, rows))
  return (
    <Panel title={`Node fleet · ${payload.machines.counts.online || 0}/${payload.machines.counts.total || machines.length} online`} active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, padding: 1 }}>
      {machines.map((machine) => {
        const online = machine.status === "online"
        const info = machine.info || {}
        const queue = typeof info.queue_depth === "number" ? info.queue_depth : (machine as Machine & { queue_depth?: number }).queue_depth
        const age = machine.name === "local" ? "now" : formatAge(machine.last_seen)
        return (
          <box key={machine.name} style={{ height: width >= 44 ? 3 : 2, flexDirection: "column", marginBottom: 1 }}>
            <box style={{ flexDirection: "row" }}>
              <text fg={online ? theme.green : theme.red} content={online ? "● " : "○ "} />
              <text fg={theme.text} attributes={1} content={truncate(machine.name, Math.max(8, width - 26))} />
              <box style={{ flexGrow: 1 }} />
              <text fg={theme.faint} content={`${machineVersion(machine)}  ${age}`} />
            </box>
            {width >= 44 && (
              <text
                fg={theme.faint}
                content={`${truncate(machine.workdir || "—", Math.max(12, width - 24))}${queue ? `  queue ${queue}` : ""}`}
              />
            )}
          </box>
        )
      })}
      {payload.machines.machines.length > machines.length && (
        <text fg={theme.blue} content={`+${payload.machines.machines.length - machines.length} more nodes`} />
      )}
      <box style={{ flexGrow: 1 }} />
      <ResourceBars system={payload.system} width={width} />
    </Panel>
  )
}

function jobDuration(job: DashboardJob, now: number): string {
  const started = Number(job.last_started_at || job.created_at || 0)
  return started ? formatDuration(Math.max(0, now - started)) : "—"
}

function WorkloadRow({
  job,
  now,
  width,
}: {
  job: DashboardJob
  now: number
  width: number
}) {
  const name = job.name || job.job_id || job.command || "tracked job"
  return (
    <box style={{ height: 2, flexDirection: "row", alignItems: "center", paddingLeft: 1, paddingRight: 1 }}>
      <text fg={statusColor(job.status)} content="● " />
      <text fg={theme.text} attributes={1} content={truncate(name, Math.max(8, width - 30))} />
      <box style={{ flexGrow: 1 }} />
      <text fg={theme.faint} content={`${(job.status || "active").padEnd(9)} ${jobDuration(job, now)}`} />
    </box>
  )
}

function SessionRow({ session, width }: { session: TerminalSession; width: number }) {
  return (
    <box style={{ height: 2, flexDirection: "row", alignItems: "center", paddingLeft: 1, paddingRight: 1 }}>
      <text fg={theme.magenta} content="◆ " />
      <text fg={theme.muted} content={truncate(session.session_id, Math.max(8, width - 22))} />
      <box style={{ flexGrow: 1 }} />
      <text fg={theme.faint} content={session.backend || "session"} />
    </box>
  )
}

function ActiveWorkloads({ payload, width, rows }: { payload: DashboardPayload; width: number; rows: number }) {
  const now = payload.generated_at
  const jobRows = payload.jobs.slice(0, Math.max(1, rows - Math.min(3, payload.sessions.length)))
  const remaining = Math.max(0, rows - jobRows.length)
  const sessions = payload.sessions.slice(0, remaining)
  return (
    <Panel title={`Active workloads · ${payload.jobs.length + payload.sessions.length}`} style={{ flexGrow: 1, paddingTop: 1 }}>
      {jobRows.length === 0 && sessions.length === 0 ? (
        <EmptyState title="No active workloads" detail="Jobs and sessions will appear here" />
      ) : (
        <box style={{ flexDirection: "column", flexGrow: 1 }}>
          {jobRows.map((job) => <WorkloadRow key={job.job_id || job.session_id || job.name} job={job} now={now} width={width} />)}
          {sessions.map((session) => <SessionRow key={session.session_id} session={session} width={width} />)}
        </box>
      )}
    </Panel>
  )
}

function Alerts({ alerts, width, rows }: { alerts: DashboardAlert[]; width: number; rows: number }) {
  const visible = alerts.slice(0, rows)
  return (
    <Panel title={`Needs attention · ${alerts.length}`} style={{ flexGrow: 1, padding: 1 }}>
      {visible.length === 0 ? (
        <box style={{ flexGrow: 1, alignItems: "center", justifyContent: "center" }}>
          <text fg={theme.green} content={width >= 44 ? "✓ No active alerts" : "✓ No issues"} />
        </box>
      ) : (
        visible.map((alert, index) => (
          <box key={`${alert.title}-${index}`} style={{ flexDirection: "column", marginBottom: 1 }}>
            <box style={{ flexDirection: "row" }}>
              <text fg={severityColor(alert.severity)} attributes={1} content={`${alert.severity.toUpperCase().slice(0, 4).padEnd(5)} `} />
              <text fg={theme.text} content={truncate(alert.title, Math.max(10, width - 11))} />
            </box>
            {width >= 34 && (
              <text fg={theme.faint} content={truncate(`${alert.detail || ""}${alert.age_s ? ` · ${formatDuration(alert.age_s)}` : ""}`, Math.max(10, width - 3))} />
            )}
          </box>
        ))
      )}
      {alerts.length > visible.length && <text fg={theme.blue} content={`+${alerts.length - visible.length} more alerts`} />}
    </Panel>
  )
}

function LargeChart({
  title,
  value,
  detail,
  values,
  color,
  width,
  height,
  rangeLabel,
}: {
  title: string
  value: string
  detail: string
  values: number[]
  color: string
  width: number
  height: number
  rangeLabel: string
}) {
  const chartWidth = Math.max(8, width - 4)
  const chartHeight = Math.max(3, Math.min(12, height - 4))
  const chart = areaChart(values, chartWidth, chartHeight).join("\n")
  return (
    <Panel title={title} style={{ flexGrow: 1, paddingLeft: 1, paddingRight: 1 }}>
      <box style={{ height: 1, flexDirection: "row" }}>
        <text fg={color} attributes={1} content={value} />
        <box style={{ flexGrow: 1 }} />
        <text fg={theme.faint} content={detail} />
      </box>
      <text fg={color} content={chart} />
      <box style={{ flexGrow: 1 }} />
      <box style={{ height: 1, flexDirection: "row" }}>
        <text fg={theme.faint} content={rangeLabel} />
        <box style={{ flexGrow: 1 }} />
        <text fg={theme.faint} content="now" />
      </box>
    </Panel>
  )
}

function SystemTrends({
  payload,
  history,
  width,
  height,
  large,
}: {
  payload: DashboardPayload
  history: TrendSample[]
  width: number
  height: number
  large: boolean
}) {
  const cpu = history.map((sample) => sample.cpu)
  const memory = history.map((sample) => sample.memory)
  const networkRaw = history.map((sample) => sample.network)
  const networkPeak = Math.max(1, ...networkRaw)
  const network = networkRaw.map((value) => (value / networkPeak) * 100)
  const chartWidth = Math.max(10, Math.floor((width - 8) / 3))
  const chartHeight = Math.max(8, height - 6)
  const rangeLabel = trendRangeLabel(history.map((sample) => sample.timestamp))

  if (!large) {
    const sparkWidth = Math.max(10, width - 27)
    return (
      <Panel title="System trends" active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, paddingLeft: 1, paddingRight: 1 }}>
        {[
          ["CPU", payload.system.cpu_percent || 0, cpu, theme.green, "%"],
          ["Memory", payload.system.memory_percent || 0, memory, theme.blue, "%"],
          ...(width >= 52 ? [["Disk", payload.system.disk_percent || 0, history.map((sample) => sample.disk), theme.magenta, "%"]] : []),
          ...(width >= 58 ? [["Network", payload.system.network_rx_bps || 0, network, theme.orange, ""]] : []),
        ].map(([label, current, values, color, suffix]) => (
          <box key={String(label)} style={{ height: 1, flexDirection: "row", alignItems: "center" }}>
            <text fg={theme.faint} content={`${String(label).padEnd(9)} `} />
            <text fg={String(color)} content={sparkline(values as number[], sparkWidth)} />
            <box style={{ flexGrow: 1 }} />
            <text fg={theme.muted} content={label === "Network" ? formatRate(Number(current)) : `${Math.round(Number(current))}${suffix}`} />
          </box>
        ))}
      </Panel>
    )
  }

  return (
    <Panel title="System trends · rolling local telemetry" active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1, padding: 1 }}>
      <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
        <LargeChart
          title="CPU utilization"
          value={`${Math.round(payload.system.cpu_percent || 0)}%`}
          detail={`load ${payload.system.load_1m ?? "—"}`}
          values={cpu}
          color={theme.green}
          width={chartWidth}
          height={chartHeight}
          rangeLabel={rangeLabel}
        />
        <LargeChart
          title="Memory pressure"
          value={`${Math.round(payload.system.memory_percent || 0)}%`}
          detail={`${formatBytes(payload.system.memory_used_bytes)} used`}
          values={memory}
          color={theme.blue}
          width={chartWidth}
          height={chartHeight}
          rangeLabel={rangeLabel}
        />
        <LargeChart
          title="Network throughput"
          value={formatRate((payload.system.network_rx_bps || 0) + (payload.system.network_tx_bps || 0))}
          detail={`peak ${formatRate(networkPeak)}`}
          values={network}
          color={theme.orange}
          width={chartWidth}
          height={chartHeight}
          rangeLabel={rangeLabel}
        />
      </box>
      <box style={{ height: 2, flexDirection: "row", alignItems: "center", paddingLeft: 1, paddingRight: 1 }}>
        <text fg={theme.magenta} content={`Disk ${Math.round(payload.system.disk_percent || 0)}%`} />
        <text fg={theme.faint} content={`  ${formatBytes(payload.system.disk_used_bytes)} / ${formatBytes(payload.system.disk_total_bytes)}`} />
        <box style={{ flexGrow: 1 }} />
        <text fg={theme.cyan} content={`RX ${formatRate(payload.system.network_rx_bps)}  TX ${formatRate(payload.system.network_tx_bps)}`} />
      </box>
    </Panel>
  )
}

function RecentActivity({ activity, width, rows }: { activity: DashboardActivity[]; width: number; rows: number }) {
  const visible = activity.slice(0, rows)
  return (
    <Panel title="Recent activity" style={{ flexGrow: 1, padding: 1 }}>
      {visible.length === 0 ? (
        <EmptyState title="No recent MCP activity" detail="Successful and failed calls will appear here" />
      ) : (
        visible.map((entry, index) => (
          <box key={`${entry.timestamp}-${entry.title}-${index}`} style={{ height: 1, flexDirection: "row", alignItems: "center" }}>
            <text fg={theme.faint} content={`${entry.timestamp ? new Date(entry.timestamp * 1000).toLocaleTimeString().slice(0, 5) : "--:--"} `} />
            <text fg={activityColor(entry.kind)} content={entry.kind === "failed" ? "× " : entry.kind === "running" ? "◌ " : "✓ "} />
            <text fg={theme.muted} content={truncate(`${entry.title} · ${entry.node}`, Math.max(8, width - 10))} />
          </box>
        ))
      )}
    </Panel>
  )
}

function QuickSystemInfo({ payload, width }: { payload: DashboardPayload; width: number }) {
  const data = [
    ["LSM", versionFrom(payload)],
    ["Platform", String(payload.version.platform || "—")],
    ["Python", String(payload.version.python || "—")],
    ["CPUs", String(payload.system.cpu_count || "—")],
    ["Load", String(payload.system.load_1m ?? "—")],
    ["Uptime", formatDuration(payload.system.uptime_s)],
    ["Sessions", String(payload.session_count)],
    ["Open todos", String(payload.todo_counts.open)],
    ["Audit 24h", String(payload.audit_total_24h)],
  ]
  return (
    <Panel title="Quick system info" style={{ flexGrow: 1, padding: 1 }}>
      {data.map(([label, value]) => (
        <box key={label} style={{ height: 1, flexDirection: "row" }}>
          <text fg={theme.faint} content={`${label.padEnd(11)} `} />
          <text fg={label === "LSM" ? theme.green : theme.muted} content={truncate(value, Math.max(6, width - 14))} />
        </box>
      ))}
    </Panel>
  )
}

function CompactDashboard({ payload, history, width, height }: { payload: DashboardPayload; history: TrendSample[]; width: number; height: number }) {
  const panelHeight = Math.max(8, Math.floor((height - 9) / 2))
  return (
    <>
      <box style={{ height: panelHeight, flexDirection: "row", gap: 1 }}>
        <box style={{ width: "42%" }}><NodeFleet payload={payload} width={Math.floor(width * 0.42)} rows={3} /></box>
        <box style={{ flexGrow: 1 }}><ActiveWorkloads payload={payload} width={Math.floor(width * 0.58)} rows={4} /></box>
      </box>
      <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
        <box style={{ width: "58%" }}><SystemTrends payload={payload} history={history} width={Math.floor(width * 0.58)} height={panelHeight} large={false} /></box>
        <box style={{ flexGrow: 1 }}><Alerts alerts={payload.alerts} width={Math.floor(width * 0.42)} rows={4} /></box>
      </box>
    </>
  )
}

function MinimalDashboard({ payload, width }: { payload: DashboardPayload; width: number }) {
  const alert = payload.alerts[0]
  const workload = payload.jobs[0]
  const session = payload.sessions[0]
  const workloadCount = payload.jobs.length + payload.sessions.length
  return (
    <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
      <Panel title="System overview" active accent={colors.accent} activeBackground={colors.panel} style={{ height: 4, paddingLeft: 1, paddingRight: 1 }}>
        <text
          fg={alert ? severityColor(alert.severity) : theme.green}
          attributes={1}
          content={truncate(alert ? `! ${alert.title}` : "✓ No active alerts", Math.max(10, width - 5))}
        />
        <text
          fg={theme.muted}
          content={`CPU ${Math.round(payload.system.cpu_percent || 0)}%  MEM ${Math.round(payload.system.memory_percent || 0)}%  DISK ${Math.round(payload.system.disk_percent || 0)}%`}
        />
      </Panel>
      <Panel title={`Active workloads · ${workloadCount}`} style={{ flexGrow: 1, paddingLeft: 1, paddingRight: 1 }}>
        {workload ? (
          <text fg={statusColor(workload.status)} content={truncate(`● ${workload.name || workload.job_id || workload.command || "tracked job"}`, Math.max(10, width - 5))} />
        ) : session ? (
          <text fg={theme.magenta} content={truncate(`◆ ${session.session_id}`, Math.max(10, width - 5))} />
        ) : (
          <text fg={theme.faint} content="No active jobs or sessions" />
        )}
      </Panel>
    </box>
  )
}

export function DashboardScreen({
  width,
  height,
  setStatus,
  keyboardEnabled,
}: {
  width: number
  height: number
  setStatus: (message: string) => void
  keyboardEnabled: boolean
}) {
  const [payload, setPayload] = useState<DashboardPayload | null>(null)
  const [history, setHistory] = useState<TrendSample[]>([])
  const [loading, setLoading] = useState(false)
  const request = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const layout = dashboardLayout(width, height)

  const refresh = useCallback(async (force = false) => {
    if (controller.current && !force) return
    controller.current?.abort()
    const nextController = new AbortController()
    controller.current = nextController
    const requestId = ++request.current
    setLoading(true)
    try {
      const next = await api.dashboard(nextController.signal)
      if (nextController.signal.aborted || requestId !== request.current) return
      setPayload(next)
      const network = (next.system.network_rx_bps || 0) + (next.system.network_tx_bps || 0)
      setHistory((current) => [
        ...current,
        {
          timestamp: next.system.timestamp || next.generated_at,
          cpu: clampPercent(next.system.cpu_percent),
          memory: clampPercent(next.system.memory_percent),
          disk: clampPercent(next.system.disk_percent),
          network,
          load: clampPercent(((next.system.load_1m || 0) / Math.max(1, next.system.cpu_count || 1)) * 100),
        },
      ].slice(-72))
      setStatus(`Dashboard ready · ${next.machines.counts.online || 0}/${next.machines.counts.total || next.machines.machines.length} nodes online`)
    } catch (error) {
      if (!nextController.signal.aborted && requestId === request.current) {
        setStatus(`Dashboard: ${formatError(error)}`)
      }
    } finally {
      if (controller.current === nextController) controller.current = null
      if (requestId === request.current) setLoading(false)
    }
  }, [setStatus])

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 3_000)
    return () => {
      request.current += 1
      controller.current?.abort()
      controller.current = null
      clearInterval(timer)
    }
  }, [refresh])

  useKeyboard((key) => {
    if (!keyboardEnabled) return
    if (key.name === "r") void refresh(true)
  })

  const denseRows = useMemo(() => Math.max(4, Math.floor((height - 12) / 3)), [height])

  if (!payload) {
    return (
      <box style={{ flexGrow: 1, flexDirection: "column" }}>
        <Panel title="Dashboard" active accent={colors.accent} activeBackground={colors.panel} style={{ flexGrow: 1 }}>
          <EmptyState title={loading ? "Collecting system snapshot" : "Dashboard unavailable"} detail="The overview will populate when the local UI API responds" />
        </Panel>
        <KeyHint accent={colors.accent} items={[{ key: "r", label: "refresh", onPress: () => void refresh(true), disabled: loading }]} />
      </box>
    )
  }

  return (
    <box style={{ flexGrow: 1, flexDirection: "column", gap: 1 }}>
      <SummaryStrip payload={payload} width={width} />
      {layout === "wide" ? (
        <>
          <box style={{ height: Math.max(13, Math.floor((height - 10) * 0.43)), flexDirection: "row", gap: 1 }}>
            <box style={{ width: "31%" }}><NodeFleet payload={payload} width={Math.floor(width * 0.31)} rows={denseRows} /></box>
            <box style={{ flexGrow: 1 }}><ActiveWorkloads payload={payload} width={Math.floor(width * 0.39)} rows={denseRows + 1} /></box>
            <box style={{ width: "29%" }}><Alerts alerts={payload.alerts} width={Math.floor(width * 0.29)} rows={denseRows} /></box>
          </box>
          <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
            <box style={{ width: "56%" }}><SystemTrends payload={payload} history={history} width={Math.floor(width * 0.56)} height={Math.max(12, Math.floor((height - 10) * 0.48))} large /></box>
            <box style={{ width: "27%" }}><RecentActivity activity={payload.activity} width={Math.floor(width * 0.27)} rows={denseRows + 2} /></box>
            <box style={{ flexGrow: 1 }}><QuickSystemInfo payload={payload} width={Math.floor(width * 0.17)} /></box>
          </box>
        </>
      ) : layout === "desktop" || layout === "compact" ? (
        <CompactDashboard payload={payload} history={history} width={width} height={height} />
      ) : (
        <MinimalDashboard payload={payload} width={width} />
      )}
      <KeyHint
        accent={colors.accent}
        items={[
          { key: "r", label: loading ? "refreshing" : "refresh", onPress: () => void refresh(true), disabled: loading || !keyboardEnabled },
          { key: "F1", label: "help" },
          { key: "Alt+1…6", label: "pages" },
        ]}
      />
    </box>
  )
}
