import { useState } from 'react';
import { RefreshCw, Square, RotateCcw } from 'lucide-react';
import useLocalize from '~/hooks/useLocalize';
import { asText, write, type RecordValue } from './api';
import { useControllerQuery } from './hooks';

type Job = RecordValue & { job_id?: string; name?: string; status?: string; command?: string };
const activeStatuses = new Set(['starting', 'running', 'stopping', 'retrying']);
const button = 'rounded px-2 py-1 text-xs hover:bg-surface-hover disabled:opacity-40';
export default function WorkspaceJobs({ machine }: { machine: string }) {
  const localize = useLocalize();
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const query = useControllerQuery<{ jobs: Job[]; next_offset?: number | null }>('jobs', { machine, limit: 50, offset }, { refetchInterval: 5000 });
  const jobs = query.data?.jobs ?? [];
  const id = jobs.some(job => job.job_id === selected) ? selected : jobs[0]?.job_id || '';
  const output = useControllerQuery<{ job?: Job; output?: string }>('jobs/output', { machine, job_id: id, lines: 200 }, { enabled: !!id, refetchInterval: 3000 });
  const job = output.data?.job ?? jobs.find(row => row.job_id === id);
  const action = async (kind: 'stop' | 'retry') => {
    if (!id || !window.confirm(localize(kind === 'stop' ? 'com_lsm_stop' : 'com_ui_retry') + ' ' + id + '?')) return;
    setBusy(true); setError('');
    try {
      const result = await write<Job>('jobs/' + kind, { machine, job_id: id });
      await query.refetch();
      if (kind === 'retry' && result.job_id) { setOffset(0); setSelected(result.job_id); }
      else await output.refetch();
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  return <div className="flex h-full min-h-0 flex-col text-xs">
    {!!(error || query.error || output.error) && <p role="alert" className="shrink-0 px-2 py-1 text-status-error">{error || String(query.error || output.error)}</p>}
    <div className="flex min-h-0 flex-1">
      <aside className="flex w-44 shrink-0 flex-col border-r border-border-light sm:w-64">
        <div className="flex shrink-0 items-center gap-1 border-b border-border-light px-2 py-1">
          <button className={button} onClick={() => setOffset(n => Math.max(0, n - 50))} disabled={!offset}>‹</button>
          <span>{offset + 1}</span>
          <button className={button} onClick={() => setOffset(query.data?.next_offset ?? offset)} disabled={query.data?.next_offset == null}>›</button>
          <span className="flex-1"/><button className={button} title={localize('com_lsm_refresh')} onClick={() => void query.refetch()}><RefreshCw size={14}/></button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {!jobs.length && <p className="p-2 text-text-secondary">{localize(query.isLoading ? 'com_lsm_loading' : 'com_lsm_nothing_to_display')}</p>}
          {jobs.map((row, index) => <button key={row.job_id || index} disabled={!row.job_id} className={'block w-full px-2 py-2 text-left hover:bg-surface-hover ' + (row.job_id === id ? 'bg-surface-active-alt' : '')} onClick={() => setSelected(row.job_id || '')}>
            <div className="truncate font-medium">{asText(row.name || row.command || row.job_id)}</div><div className="truncate text-text-secondary">{asText(row.status || '')}</div>
          </button>)}
        </div>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center gap-1 border-b border-border-light px-2 py-1">
          <span className="min-w-0 flex-1 truncate">{job ? asText(job.name || job.job_id) : localize('com_lsm_workspace_job_output')}</span>
          <button className={button} title={localize('com_lsm_stop')} aria-label={localize('com_lsm_stop')} disabled={busy || !job || !activeStatuses.has(String(job.status))} onClick={() => void action('stop')}><Square size={14}/></button>
          <button className={button} title={localize('com_ui_retry')} aria-label={localize('com_ui_retry')} disabled={busy || !job || activeStatuses.has(String(job.status))} onClick={() => void action('retry')}><RotateCcw size={14}/></button>
        </header>
        <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-all bg-surface-primary-alt p-2 font-mono">{output.data?.output || ''}</pre>
      </section>
    </div>
  </div>;
}
