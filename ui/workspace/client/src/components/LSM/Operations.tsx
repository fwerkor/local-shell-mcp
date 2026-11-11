import useLocalize from '~/hooks/useLocalize';
import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Play, RefreshCw, Send, Square, Server, Trash2, Plus, Search } from 'lucide-react';
import { asText, type RecordValue } from './api';
import { useControllerServices } from './hooks';

type View = 'terminals' | 'sessions' | 'remotes' | 'audit';
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
  const [selectedMachine, setSelectedMachine] = useState('');
  const [payloadMachine, setPayloadMachine] = useState('');
  const requestVersion = useRef(0);
  const [detail, setDetail] = useState<RecordValue | null>(null);
  const [machine, setMachine] = useState('local');
  const [machines, setMachines] = useState<string[]>(['local']);
  const [input, setInput] = useState('');
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState<Invite | null>(null);
  const [refreshId, setRefreshId] = useState(0);

  const refresh = async () => {
    const version = ++requestVersion.current;
    const requestedMachine = machine;
    setPayload(null);
    setBusy(true);
    try {
      const path = section === 'sessions' ? 'logical-sessions' : section;
      const data = await read<RecordValue>(path, section === 'terminals' ? { machine: requestedMachine } : section === 'audit' ? { limit: 150, search: filter } : {});
      if (requestVersion.current !== version) return;
      setPayload(data); setPayloadMachine(requestedMachine); setError('');
    } catch (e) {
      if (requestVersion.current === version) setError(String(e));
    } finally {
      if (requestVersion.current === version) setBusy(false);
    }
  };
  useEffect(() => {
    void refresh();
    if (section === 'terminals' || section === 'remotes') {
      void read<{ machines?: RecordValue[] }>('machines').then(data => {
        setMachines(['local', ...(data.machines ?? []).map(item => String(item.machine || item.name || item.id || '')).filter(v => v && v !== 'local')]);
      }).catch(() => {});
    }
    return () => { ++requestVersion.current; };
  }, [section, machine, refreshId]);
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
  const [terminalText, setTerminalText] = useState('');
  useEffect(() => {
    if (section !== 'terminals' || !selected) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await read<RecordValue>('terminals/read', { machine, session_id: selected, lines: 400 });
        if (!cancelled) setTerminalText(String(result.output ?? result.text ?? result.content ?? JSON.stringify(result, null, 2)));
      } catch (e) { if (!cancelled) setError(String(e)); }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2200);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [section, selected, machine]);

  const terminalRows = payloadMachine === machine ? ((payload?.sessions as RecordValue[] | undefined) ?? []) : [];
  const sessionRows = (payload?.sessions as RecordValue[] | undefined) ?? [];
  const remoteRows = (payload?.machines as RecordValue[] | undefined) ?? [];
  const auditRows = (payload?.entries as RecordValue[] | undefined) ?? [];
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-xl font-semibold">{section === 'terminals' ? localize('com_lsm_persistent_terminals') : section === 'sessions' ? localize('com_lsm_logical_sessions') : section === 'remotes' ? localize('com_lsm_remotes') : localize('com_lsm_audit_trail')}</h2>
        <p className="mt-1 text-sm text-text-secondary">
          {section === 'terminals' ? localize('com_lsm_manage_persistent_shells_on_your_machines') : section === 'sessions' ? localize('com_lsm_track_and_control_logical_workloads') : section === 'remotes' ? localize('com_lsm_inspect_and_manage_connected_workers') : localize('com_lsm_inspect_controller_events_and_tool_calls')}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {section === 'terminals' && <select aria-label={localize('com_lsm_terminal_machine')} className={btn} value={machine} onChange={e => { ++requestVersion.current; setPayload(null); setPayloadMachine(''); setSelected(''); setSelectedMachine(''); setDetail(null); setTerminalText(''); setMachine(e.target.value); }}>
          {machines.map(m => <option key={m} value={m}>{m}</option>)}
        </select>}
        {section === 'terminals' && <button className={btn} disabled={busy} onClick={() => void act('terminals/start', { machine, cwd: '.' })}><Plus size={16} className="mr-1 inline" />{localize('com_lsm_new_shell')}</button>}
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
        <h3 className="mb-3 text-sm font-semibold">{section === 'terminals' ? localize('com_lsm_shell_sessions') : section === 'sessions' ? localize('com_lsm_session_history') : section === 'remotes' ? localize('com_lsm_workers') : localize('com_lsm_events')}</h3>
        {(() => {
          const items = section === 'terminals' ? terminalRows : section === 'sessions' ? sessionRows : section === 'remotes' ? remoteRows : auditRows;
          if (!payload) return <p className="text-sm text-text-secondary">{localize('com_lsm_loading')}</p>;
          if (items.length === 0) return <p className="text-sm text-text-secondary">{localize('com_lsm_nothing_to_display')}</p>;
          return items.map((item, i) => {
            const id = keyFor(item, i);
            return <button key={id + i} className={row + (selected === id ? ' bg-surface-active-alt' : '')}
              onClick={() => {
                setSelected(id); setSelectedMachine(section === 'terminals' ? machine : ''); setDetail(item);
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
        {!!selected && section === 'terminals' && selectedMachine === machine && <>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 className="truncate text-sm font-semibold">{selected}</h3>
            <button className={btn} disabled={busy} onClick={() => { if (window.confirm(localize('com_lsm_terminate_this_shell'))) void act('terminals/kill', { machine, session_id: selected }, true); }}>
              <Square size={15} className="mr-1 inline" />{localize('com_lsm_stop')}
            </button>
          </div>
          <pre className="h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-primary-alt p-3 font-mono text-xs leading-5 text-text-primary" aria-label={localize('com_lsm_terminal_output')}>
            {terminalText || localize('com_lsm_no_output_yet')}
          </pre>
          <form className="mt-3 flex gap-2" onSubmit={e => { e.preventDefault(); if (!input) return; void act('terminals/send', { machine, session_id: selected, input_text: input, enter: true }); setInput(''); }}>
            <input value={input} onChange={e => setInput(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 font-mono text-sm"
              aria-label={localize('com_lsm_shell_input')} placeholder={localize('com_lsm_send_input_to_shell')} />
            <button type="submit" className={btn} disabled={busy || !input}><Send size={16} /></button>
          </form>
        </>}
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
