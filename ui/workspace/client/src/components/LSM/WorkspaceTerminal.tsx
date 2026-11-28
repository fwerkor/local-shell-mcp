import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { Plus, RefreshCw, TerminalSquare, Trash2 } from 'lucide-react';
import useLocalize from '~/hooks/useLocalize';
import { useAuthContext } from '~/hooks';
import { write } from './api';
import { useControllerQuery } from './hooks';
import { workspaceSocket, type WorkspaceConnection } from './workspaceTransport';

type Shell = { session_id: string; name?: string; cwd?: string };
const button = 'rounded p-1.5 hover:bg-surface-hover disabled:opacity-40';

function ShellView({ machine, id, connection }: { machine: string; id: string; connection: WorkspaceConnection }) {
  const localize = useLocalize();
  const { token } = useAuthContext();
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  useEffect(() => {
    if (!host.current) return;
    const term = new Terminal({ cursorBlink: true, scrollback: 12000, fontSize: 13,
      theme: { background: '#171717', foreground: '#e5e5e5', cursor: '#e5e5e5' } });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host.current);
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    let delay = 500;
    const resize = () => {
      if (!host.current?.clientHeight || !host.current?.clientWidth) return;
      try { fit.fit(); } catch { return; }
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      }
    };
    const attach = () => {
      if (stopped) return;
      resize();
      setStatus('connecting');
      const ws = workspaceSocket(connection, token, 'shell', {
        machine, session_id: id, cols: String(term.cols), rows: String(term.rows),
      });
      socket = ws;
      ws.binaryType = 'arraybuffer';
      ws.onopen = () => {
        if (stopped || socket !== ws) return;
        delay = 500;
        term.reset();
        setStatus('connected');
        resize();
      };
      ws.onmessage = event => {
        if (stopped || socket !== ws) return;
        if (event.data instanceof ArrayBuffer) term.write(new Uint8Array(event.data));
        else if (typeof event.data === 'string') term.write(event.data);
      };
      ws.onclose = event => {
        if (stopped || socket !== ws) return;
        setStatus('disconnected');
        if (event.code === 4401 || event.code === 4403 || event.code === 4411 || event.code === 4429 || event.code === 1000) return;
        retry = setTimeout(attach, delay);
        delay = Math.min(delay * 2, 10000);
      };
    };
    const input = term.onData(data => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(new TextEncoder().encode(data));
    });
    const observer = new ResizeObserver(resize);
    observer.observe(host.current);
    attach();
    return () => {
      stopped = true;
      clearTimeout(retry);
      observer.disconnect();
      socket?.close();
      input.dispose();
      term.dispose();
    };
  }, [machine, id, connection.ui_path, connection.auth_mode, token]);
  return <div className="relative h-full min-h-0 min-w-0 flex-1 bg-[#171717]">
    <div ref={host} className="absolute inset-0 overflow-hidden p-1" />
    {status !== 'connected' && <span className="pointer-events-none absolute right-3 top-1 rounded bg-neutral-800 px-2 py-1 text-xs text-white">{localize(status === 'connecting' ? 'com_lsm_workspace_connecting' : 'com_lsm_workspace_disconnected')}</span>}
  </div>;
}

export default function WorkspaceTerminal({ machine, cwd, connection }: { machine: string; cwd: string; connection: WorkspaceConnection }) {
  const localize = useLocalize();
  const query = useControllerQuery<{ sessions: Shell[] }>('terminals', { machine }, { refetchInterval: 5000 });
  const sessions = query.data?.sessions ?? [];
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [generation, setGeneration] = useState(0);
  const id = sessions.some(row => row.session_id === selected) ? selected : sessions[0]?.session_id;
  const create = async () => {
    setBusy(true); setError('');
    try {
      const result = await write<{ session_id?: string }>('terminals/start', { machine, cwd });
      await query.refetch();
      if (result.session_id) setSelected(result.session_id);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!id || !window.confirm(localize('com_lsm_terminate_this_shell'))) return;
    setBusy(true); setError('');
    try { await write('terminals/kill', { machine, session_id: id }); await query.refetch(); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  return <div className="flex h-full min-h-0 flex-col">
    {!!(error || query.error) && <p role="alert" className="shrink-0 px-2 text-xs text-status-error">{error || String(query.error)}</p>}
    <div className="flex min-h-0 flex-1">
      {id ? <ShellView key={id + ':' + generation} machine={machine} id={id} connection={connection} /> :
        <div className="flex flex-1 items-center justify-center text-sm text-text-secondary"><button className="rounded border border-border-medium px-3 py-2" onClick={() => void create()} disabled={busy}>{localize('com_lsm_new_shell')}</button></div>}
      <aside className="flex w-36 shrink-0 flex-col border-l border-border-light sm:w-48">
        <div className="flex items-center gap-1 p-1">
          <button className={button} title={localize('com_lsm_new_shell')} aria-label={localize('com_lsm_new_shell')} disabled={busy} onClick={() => void create()}><Plus size={16} /></button>
          <button className={button} title={localize('com_lsm_workspace_reconnect')} aria-label={localize('com_lsm_workspace_reconnect')} disabled={!id} onClick={() => setGeneration(n => n + 1)}><RefreshCw size={16} /></button>
          <button className={button} title={localize('com_lsm_stop')} aria-label={localize('com_lsm_stop')} disabled={busy || !id} onClick={() => void remove()}><Trash2 size={16} /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {sessions.map(shell => <button key={shell.session_id} onClick={() => setSelected(shell.session_id)} title={shell.cwd || shell.session_id} className={'flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs hover:bg-surface-hover ' + (id === shell.session_id ? 'bg-surface-active-alt' : '')}><TerminalSquare size={14} className="shrink-0"/><span className="truncate">{shell.name || shell.session_id}</span></button>)}
        </div>
      </aside>
    </div>
  </div>;
}
