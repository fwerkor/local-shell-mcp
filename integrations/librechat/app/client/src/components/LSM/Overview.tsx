import useLocalize from '~/hooks/useLocalize';
import { useEffect, useState } from 'react';
import { Activity, AlertCircle, ArrowUpRight, CheckCircle2, RefreshCw, Server, TerminalSquare, HardDrive, Clock3 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { asText, type RecordValue } from './api';
import { useControllerServices } from './hooks';

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
  const localize = useLocalize();
  const { read, write } = useControllerServices();
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
        <h2 className="text-xl font-semibold">{localize('com_lsm_workspace_overview')}</h2>
        <p className="mt-1 text-sm text-text-secondary">{localize('com_lsm_your_controller_machines_and_active_work_in_one_place')}</p>
      </div>
      <button type="button" onClick={() => void refresh()} disabled={busy}
        className="inline-flex items-center gap-2 rounded-lg border border-border-medium px-3 py-2 text-sm hover:bg-surface-hover disabled:opacity-50">
        <RefreshCw size={16} className={busy ? 'animate-spin' : ''} /> {localize('com_lsm_refresh')}
      </button>
    </div>
    {error && <div role="alert" className="rounded-lg border border-status-error-border bg-status-error-subtle p-3 text-sm text-status-error">{error}</div>}
    {!snapshot && !error && <p className="py-12 text-center text-sm text-text-secondary">{localize('com_lsm_loading_controller_status')}</p>}
    {snapshot && <>
      <div className="flex items-center gap-3 rounded-xl border border-border-light bg-surface-secondary p-4">
        {snapshot.health === 'healthy' ? <CheckCircle2 size={21} className="text-status-success" /> : <AlertCircle size={21} className="text-status-warning" />}
        <div className="flex-1"><strong className="text-sm">{localize('com_lsm_controller')} {snapshot.health ?? localize('com_lsm_unknown')}</strong>
          <div className="text-xs text-text-secondary">
            {localize('com_lsm_version')} {asText(snapshot.version?.version)} · {snapshot.generated_at ? new Date(snapshot.generated_at * 1000).toLocaleString() : localize('com_lsm_no_snapshot')}
          </div>
        </div>
        <Link to="/control/audit" aria-label={localize('com_lsm_open_audit')}><ArrowUpRight size={19} /></Link>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={localize('com_lsm_connected_machines')} value={String(online) + ' / ' + machines.length} icon={Server} link="/control/remotes" />
        <Metric label={localize('com_lsm_running_jobs')} value={String(snapshot.jobs?.length ?? 0)} icon={Activity} link="/control/terminals" />
        <Metric label={localize('com_lsm_persistent_shells')} value={String(snapshot.session_count ?? snapshot.sessions?.length ?? 0)} icon={TerminalSquare} link="/control/terminals" />
        <Metric label={localize('com_lsm_events_24_hours')} value={String(snapshot.audit_total_24h ?? 0)} icon={Clock3} link="/control/audit" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <section className={panel}>
          <div className="mb-4 flex items-center justify-between"><h3 className="font-semibold">{localize('com_lsm_active_jobs')}</h3><Link to="/control/terminals" className="text-xs text-text-secondary hover:underline">{localize('com_lsm_open_terminals')}</Link></div>
          {(snapshot.jobs ?? []).length === 0 && <p className="text-sm text-text-secondary">{localize('com_lsm_no_active_jobs')}</p>}
          {(snapshot.jobs ?? []).slice(0, 8).map((job, i) => (
            <div key={String(job.job_id ?? i)} className="flex items-center justify-between gap-2 border-b border-border-light py-3 last:border-0">
              <div className="min-w-0"><div className="truncate text-sm font-medium">{asText(job.name || job.command || job.job_id)}</div>
                <div className="text-xs text-text-secondary">{asText(job.machine || 'local')}</div></div>
              <span className="rounded-full bg-surface-secondary px-2 py-1 text-xs">{asText(job.status)}</span>
            </div>
          ))}
        </section>
        <section className={panel}>
          <h3 className="mb-4 font-semibold">{localize('com_lsm_attention')}</h3>
          {(snapshot.alerts ?? []).length === 0 && <p className="flex items-center gap-2 text-sm text-text-secondary"><CheckCircle2 size={17} /> {localize('com_lsm_no_active_alerts')}</p>}
          {(snapshot.alerts ?? []).map((alert, i) => (
            <div key={i} className="border-b border-border-light py-3 last:border-0">
              <div className="flex items-center gap-2 text-sm font-medium"><AlertCircle size={16} />{asText(alert.title)}</div>
              <p className="mt-1 text-xs text-text-secondary">{asText(alert.detail)}</p>
            </div>
          ))}
        </section>
        <section className={panel}>
          <div className="mb-4 flex items-center justify-between"><h3 className="font-semibold">{localize('com_lsm_machines')}</h3><Link to="/control/remotes" className="text-xs text-text-secondary hover:underline">{localize('com_lsm_all_remotes')}</Link></div>
          {(machines.length ? machines : [{ name: 'local', status: 'local' }]).map((machine, i) => (
            <div key={String(machine.machine ?? machine.name ?? i)} className="flex items-center gap-3 border-b border-border-light py-3 last:border-0">
              <Server size={17} className="text-text-secondary" /><span className="flex-1 truncate text-sm">{asText(machine.name || machine.machine)}</span>
              <span className="text-xs text-text-secondary">{asText(machine.status ?? (machine.online ? 'online' : 'offline'))}</span>
            </div>
          ))}
        </section>
        <section className={panel}>
          <h3 className="mb-4 font-semibold">{localize('com_lsm_system')}</h3>
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
