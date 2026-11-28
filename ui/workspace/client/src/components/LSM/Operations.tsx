import useLocalize from '~/hooks/useLocalize';
import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, RefreshCw, Square, Trash2, Plus, Search } from 'lucide-react';
import { asText, type RecordValue } from './api';
import { useControllerServices } from './hooks';

type View = 'sessions' | 'remotes' | 'audit';
type Invite = { name?: string; code: string; command: string; persistent_command?: string; powershell_command: string; powershell_persistent_command?: string; expires_at?: number };
const btn = 'rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm hover:bg-surface-hover disabled:opacity-40';
const block = 'rounded-xl border border-border-light bg-surface-primary p-4';
const row = 'w-full rounded-lg px-3 py-3 text-left text-sm transition-colors hover:bg-surface-hover';
const keyFor = (data: RecordValue, fallback: number) =>
  String(data.session_id || data.machine || data.name || data.id || data.job_id || fallback);
const labelFor = (data: RecordValue) => asText(data.name || data.label || data.session_id || data.machine || data.event || data.id);
export default function Operations({ section }: { section: View }) {
  const localize = useLocalize();
  const { read, write } = useControllerServices();
  const [payload, setPayload] = useState<RecordValue | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState('');
  const requestVersion = useRef(0);
  const [detail, setDetail] = useState<RecordValue | null>(null);
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState<Invite | null>(null);
  const [refreshId, setRefreshId] = useState(0);

  const refresh = async () => {
    const version = ++requestVersion.current;
    setPayload(null);
    setBusy(true);
    try {
      const path = section === 'sessions' ? 'logical-sessions' : section;
      const data = await read<RecordValue>(path, section === 'audit' ? { limit: 150, search: filter } : {});
      if (requestVersion.current !== version) return;
      setPayload(data); setError('');
    } catch (e) {
      if (requestVersion.current === version) setError(String(e));
    } finally {
      if (requestVersion.current === version) setBusy(false);
    }
  };
  useEffect(() => {
    void refresh();
    return () => { ++requestVersion.current; };
  }, [section, refreshId]);
  const act = async (path: string, data: RecordValue, clear = false) => {
    setBusy(true);
    try {
      const result = await write<RecordValue>(path, data);
      if (path === 'remotes' && typeof result.code === 'string' &&
          typeof result.command === 'string' && typeof result.powershell_command === 'string') {
        setInvite(result as Invite);
      }
      setError('');
      if (clear) { setSelected(''); setDetail(null); }
      setRefreshId(n => n + 1);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const inspect = async (path: string, params: Record<string, string>) => {
    try { setDetail(await read<RecordValue>(path, params)); setError(''); }
    catch (e) { setError(String(e)); }
  };
  const sessionRows = (payload?.sessions as RecordValue[] | undefined) ?? [];
  const remoteRows = (payload?.machines as RecordValue[] | undefined) ?? [];
  const auditRows = (payload?.entries as RecordValue[] | undefined) ?? [];
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-xl font-semibold">{section === 'sessions' ? localize('com_lsm_logical_sessions') : section === 'remotes' ? localize('com_lsm_remotes') : localize('com_lsm_audit_trail')}</h2>
        <p className="mt-1 text-sm text-text-secondary">
          {section === 'sessions' ? localize('com_lsm_track_and_control_logical_workloads') : section === 'remotes' ? localize('com_lsm_inspect_and_manage_connected_workers') : localize('com_lsm_inspect_controller_events_and_tool_calls')}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {section === 'remotes' && <button className={btn} disabled={busy} onClick={() => {
          const name = window.prompt(localize('com_lsm_new_remote_invite_name')); if (name) void act('remotes', { name });
        }}><Plus size={16} className="mr-1 inline" />{localize('com_lsm_invite')}</button>}
        {section === 'sessions' && <button className={btn} disabled={busy} onClick={() => {
          const label = window.prompt(localize('com_lsm_session_label')); if (label) void act('logical-sessions/start', { label });
        }}><Plus size={16} className="mr-1 inline" />{localize('com_lsm_new_session')}</button>}
        <button className={btn} disabled={busy} onClick={() => setRefreshId(n => n + 1)}><RefreshCw size={16} className={busy ? 'animate-spin' : ''} aria-label={localize('com_lsm_refresh')} /></button>
      </div>
    </div>
    {section === 'remotes' && invite && <section className={block + ' space-y-3'} aria-label={localize('com_lsm_remote_enrollment')}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{localize('com_lsm_enroll')} {invite.name || localize('com_lsm_remote')} · {localize('com_lsm_invitation')} {invite.code}</h3>
        <button className={btn} onClick={() => setInvite(null)}>{localize('com_lsm_dismiss')}</button>
      </div>
      <p className="text-xs text-text-secondary">{localize('com_lsm_these_one_time_credentials_will_not_be_shown_again_copy_the_command_to_the_new_machine')}</p>
      {([['Linux / macOS', invite.command], ['Windows PowerShell', invite.powershell_command]] as const).map(([label, command]) =>
        <div key={label} className="space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium">{label}</span>
            <button className={btn} onClick={() => void navigator.clipboard.writeText(command)}>{localize('com_lsm_copy_command')}</button>
          </div>
          <pre className="overflow-auto rounded-lg bg-surface-primary-alt p-3 font-mono text-xs">{command}</pre>
        </div>)}
    </section>}
    {section === 'audit' && <form onSubmit={e => { e.preventDefault(); setRefreshId(n => n + 1); }} className="flex gap-2">
      <input value={filter} onChange={e => setFilter(e.target.value)} placeholder={localize('com_lsm_search_events')} aria-label={localize('com_lsm_search_audit')}
        className="min-w-0 flex-1 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm" />
      <button className={btn} type="submit"><Search size={16} className="mr-1 inline" />{localize('com_lsm_search')}</button>
    </form>}
    {error && <p role="alert" className="rounded-lg border border-status-error-border bg-status-error-subtle p-3 text-sm text-status-error">{error}</p>}
    <div className="grid min-h-52 gap-4 lg:grid-cols-[minmax(245px,0.8fr)_minmax(320px,1.2fr)]">
      <section className={block + ' max-h-[70vh] overflow-auto'}>
        <h3 className="mb-3 text-sm font-semibold">{section === 'sessions' ? localize('com_lsm_session_history') : section === 'remotes' ? localize('com_lsm_workers') : localize('com_lsm_events')}</h3>
        {(() => {
          const items = section === 'sessions' ? sessionRows : section === 'remotes' ? remoteRows : auditRows;
          if (!payload) return <p className="text-sm text-text-secondary">{localize('com_lsm_loading')}</p>;
          if (items.length === 0) return <p className="text-sm text-text-secondary">{localize('com_lsm_nothing_to_display')}</p>;
          return items.map((item, i) => {
            const id = keyFor(item, i);
            return <button key={id + i} className={row + (selected === id ? ' bg-surface-active-alt' : '')}
              onClick={() => {
                setSelected(id); setDetail(item);
                if (section === 'sessions') void inspect('logical-sessions/detail', { session_id: id });
                if (section === 'audit') void inspect('audit/detail', { id });
              }}>
              <div className="flex items-center justify-between gap-2">
                <strong className="truncate font-medium">{labelFor(item)}</strong>
                <span className="shrink-0 text-xs text-text-secondary">{asText(item.status || item.severity || '')}</span>
              </div>
              <div className="mt-1 truncate text-xs text-text-secondary">
                {asText(item.machine || item.operation || item.objective || item.updated_at || item.created_at || '')}
              </div>
            </button>;
          });
        })()}
      </section>
      <section className={block + ' min-w-0'}>
        {!selected && <p className="py-8 text-center text-sm text-text-secondary">{localize('com_lsm_select_an_item_to_inspect_it')}</p>}
        {!!selected && section === 'sessions' && <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h3 className="mr-auto text-sm font-semibold">{localize('com_lsm_session_detail')}</h3>
            {['finish', 'cancel'].map(action => <button key={action} className={btn} disabled={busy}
              onClick={() => { if (window.confirm(action + ' ' + localize('com_lsm_session'))) void act('logical-sessions/' + action, { session_id: selected }); }}>
              {action === 'finish' ? <CheckCircle2 size={15} className="mr-1 inline" /> : <Square size={15} className="mr-1 inline" />}{localize(action === 'finish' ? 'com_lsm_finish' : 'com_lsm_cancel')}
            </button>)}
          </div>
          <pre className="max-h-[58vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-primary-alt p-3 font-mono text-xs">{JSON.stringify(detail, null, 2)}</pre>
        </>}
        {!!selected && section === 'remotes' && <>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">{labelFor(detail || {})}</h3>
            <div className="flex gap-2">
              <button className={btn} disabled={busy} onClick={() => {
                const name = window.prompt(localize('com_lsm_rename_worker')); if (name) void act('remotes/rename', { machine: selected, new_name: name });
              }}>{localize('com_lsm_rename')}</button>
              <button className={btn} disabled={busy} onClick={() => { if (window.confirm(localize('com_lsm_revoke_this_worker'))) void act('remotes/revoke', { machine: selected }, true); }}>
                <Trash2 size={15} />
              </button>
            </div>
          </div>
          <pre className="max-h-[58vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-primary-alt p-3 font-mono text-xs">{JSON.stringify(detail, null, 2)}</pre>
        </>}
        {!!selected && section === 'audit' && <>
          <h3 className="mb-3 text-sm font-semibold">{localize('com_lsm_event_detail')}</h3>
          <pre className="max-h-[58vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-primary-alt p-3 font-mono text-xs">{JSON.stringify(detail, null, 2)}</pre>
        </>}
      </section>
    </div>
  </div>;
}
