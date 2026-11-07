import { useEffect, useState } from 'react';
import { Activity, AlertCircle, ArrowUpRight, CheckCircle2, RefreshCw, Server, TerminalSquare, HardDrive, Clock3 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { read, asText, formatBytes, type RecordValue } from './api';

const panel = 'rounded-2xl border border-border-light bg-surface-primary p-5';
type Snapshot = {
  health?: string;
  generated_at?: number;
  system?: RecordValue;
  machines?: { machines?: RecordValue[] };
  jobs?: RecordValue[];
  sessions?: RecordValue[];
  alerts?: RecordValue[];
  activity?: RecordValue[];
  job_counts?: RecordValue;
  session_count?: number;
  audit_total_24h?: number;
  version?: RecordValue;
};
function Metric({ label, value, icon: Icon, link }: {
  label: string; value: string; icon: typeof Activity; link: string;
}) {
  return <Link to={link} className={panel + ' flex items-center justify-between gap-3 transition-colors hover:bg-surface-hover'}>
    <div><div className="text-xs text-text-secondary">{label}</div><strong className="mt-2 block text-2xl font-semibold">{value}</strong></div>
    <span className="rounded-xl bg-surface-secondary p-3 text-text-secondary"><Icon size={22} /></span>
  </Link>;
}
export default function Overview() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true);
    try {
      setSnapshot(await read<Snapshot>('dashboard'));
      setError('');
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  useEffect(() => { void refresh(); }, []);
  const machines = snapshot?.machines?.machines ?? [];
  const online = machines.filter((m) => m.online === true || m.status === 'online').length;
  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="text-xl font-semibold">Workspace overview</h2>
        <p className="mt-1 text-sm text-text-secondary">Your Controller, machines and active work in one place.</p>
      </div>
      <button type="button" onClick={() => void refresh()} disabled={busy}
        className="inline-flex items-center gap-2 rounded-lg border border-border-medium px-3 py-2 text-sm hover:bg-surface-hover disabled:opacity-50">
        <RefreshCw size={16} className={busy ? 'animate-spin' : ''} /> Refresh
      </button>
    </div>
    {error && <div role="alert" className="rounded-lg border border-red-400/40 p-3 text-sm text-red-500">{error}</div>}
    {!snapshot && !error && <p className="py-12 text-center text-sm text-text-secondary">Loading Controller status…</p>}
    {snapshot && <>
      <div className="flex items-center gap-3 rounded-xl border border-border-light bg-surface-secondary p-4">
        {snapshot.health === 'healthy' ? <CheckCircle2 size={21} className="text-green-500" /> : <AlertCircle size={21} className="text-amber-500" />}
        <div className="flex-1"><strong className="text-sm">Controller {snapshot.health ?? 'unknown'}</strong>
          <div className="text-xs text-text-secondary">
            Version {asText(snapshot.version?.version)} · {snapshot.generated_at ? new Date(snapshot.generated_at * 1000).toLocaleString() : 'No snapshot'}
          </div>
        </div>
        <Link to="/control/audit" aria-label="Open audit"><ArrowUpRight size={19} /></Link>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Connected machines" value={String(online) + ' / ' + machines.length} icon={Server} link="/control/remotes" />
        <Metric label="Running jobs" value={String(snapshot.jobs?.length ?? 0)} icon={Activity} link="/control/terminals" />
        <Metric label="Persistent shells" value={String(snapshot.session_count ?? snapshot.sessions?.length ?? 0)} icon={TerminalSquare} link="/control/terminals" />
        <Metric label="Events (24 hours)" value={String(snapshot.audit_total_24h ?? 0)} icon={Clock3} link="/control/audit" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <section className={panel}>
          <div className="mb-4 flex items-center justify-between"><h3 className="font-semibold">Active jobs</h3><Link to="/control/terminals" className="text-xs text-text-secondary hover:underline">Open terminals</Link></div>
          {(snapshot.jobs ?? []).length === 0 && <p className="text-sm text-text-secondary">No active jobs</p>}
          {(snapshot.jobs ?? []).slice(0, 8).map((job, i) => (
            <div key={String(job.job_id ?? i)} className="flex items-center justify-between gap-2 border-b border-border-light py-3 last:border-0">
              <div className="min-w-0"><div className="truncate text-sm font-medium">{asText(job.name || job.command || job.job_id)}</div>
                <div className="text-xs text-text-secondary">{asText(job.machine || 'local')}</div></div>
              <span className="rounded-full bg-surface-secondary px-2 py-1 text-xs">{asText(job.status)}</span>
            </div>
          ))}
        </section>
        <section className={panel}>
          <h3 className="mb-4 font-semibold">Attention</h3>
          {(snapshot.alerts ?? []).length === 0 && <p className="flex items-center gap-2 text-sm text-text-secondary"><CheckCircle2 size={17} /> No active alerts</p>}
          {(snapshot.alerts ?? []).map((alert, i) => (
            <div key={i} className="border-b border-border-light py-3 last:border-0">
              <div className="flex items-center gap-2 text-sm font-medium"><AlertCircle size={16} />{asText(alert.title)}</div>
              <p className="mt-1 text-xs text-text-secondary">{asText(alert.detail)}</p>
            </div>
          ))}
        </section>
        <section className={panel}>
          <div className="mb-4 flex items-center justify-between"><h3 className="font-semibold">Machines</h3><Link to="/control/remotes" className="text-xs text-text-secondary hover:underline">All remotes</Link></div>
          {(machines.length ? machines : [{ name: 'local', status: 'local' }]).map((machine, i) => (
            <div key={String(machine.machine ?? machine.name ?? i)} className="flex items-center gap-3 border-b border-border-light py-3 last:border-0">
              <Server size={17} className="text-text-secondary" /><span className="flex-1 truncate text-sm">{asText(machine.name || machine.machine)}</span>
              <span className="text-xs text-text-secondary">{asText(machine.status ?? (machine.online ? 'online' : 'offline'))}</span>
            </div>
          ))}
        </section>
        <section className={panel}>
          <h3 className="mb-4 font-semibold">System</h3>
          <div className="space-y-3">
            {Object.entries(snapshot.system ?? {}).filter(([key, value]) => /cpu|memory|disk|load|uptime/i.test(key) && (typeof value !== 'object' || value == null)).slice(0, 8).map(([key, value]) =>
              <div key={key} className="flex items-center justify-between gap-3 text-sm">
                <span className="capitalize text-text-secondary">{key.replaceAll('_', ' ')}</span><span className="font-medium">{asText(value)}</span>
              </div>)}
          </div>
          {Object.keys(snapshot.system ?? {}).length === 0 && <p className="text-sm text-text-secondary">System details unavailable</p>}
        </section>
      </div>
    </>}
  </div>;
}
