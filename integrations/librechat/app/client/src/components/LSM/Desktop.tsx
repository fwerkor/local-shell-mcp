import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Keyboard, Monitor, MousePointer2, RefreshCw } from 'lucide-react';
import { useAuthContext } from '~/hooks';
import { asText, binaryRequest, qs, read, write, type RecordValue } from './api';

type Bounds = { x: number; y: number; width: number; height: number };
type Observation = { id: string; bounds: Bounds; coordinateInput: boolean };
const button = 'rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm hover:bg-surface-hover disabled:opacity-40';
export default function Desktop() {
  const { token } = useAuthContext();
  const [machine, setMachine] = useState('local');
  const [machines, setMachines] = useState<string[]>(['local']);
  const [windows, setWindows] = useState<RecordValue[]>([]);
  const [windowId, setWindowId] = useState('');
  const [image, setImage] = useState('');
  const [observation, setObservation] = useState<Observation | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [keys, setKeys] = useState('');
  const imageRef = useRef<HTMLImageElement>(null);
  const urlRef = useRef('');
  useEffect(() => {
    void read<{ machines?: RecordValue[] }>('machines').then(data => {
      setMachines(['local', ...(data.machines ?? []).map(row => String(row.machine || row.name || row.id || '')).filter(m => m && m !== 'local')]);
    }).catch(() => {});
    return () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current); };
  }, []);
  const refreshWindows = async (target = machine) => {
    setBusy(true);
    try {
      const result = await read<{ windows?: RecordValue[] }>('gui/windows', { machine: target });
      setWindows(result.windows || []); setError('');
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  useEffect(() => { setWindowId(''); setImage(''); setObservation(null); void refreshWindows(); }, [machine]);
  const frame = async (id = windowId) => {
    if (!id) return;
    setBusy(true);
    try {
      const response = await binaryRequest('gui/frame' + qs({ machine, window_id: id }), token);
      if (!(response.headers.get('content-type') || '').startsWith('image/')) {
        throw new Error('Controller returned no display frame');
      }
      const bounds: Bounds = {
        x: Number(response.headers.get('x-lsm-gui-window-x') || 0),
        y: Number(response.headers.get('x-lsm-gui-window-y') || 0),
        width: Number(response.headers.get('x-lsm-gui-window-width') || 0),
        height: Number(response.headers.get('x-lsm-gui-window-height') || 0),
      };
      const next = URL.createObjectURL(await response.blob());
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = next; setImage(next);
      setObservation({ id: response.headers.get('x-lsm-gui-observation-id') || '', bounds,
        coordinateInput: response.headers.get('x-lsm-gui-coordinate-input') === '1' });
      setError('');
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const act = async (action: RecordValue) => {
    if (!observation || !windowId) return;
    setBusy(true);
    try {
      await write('gui/action', { machine, window_id: windowId, observation_id: observation.id, bounds: observation.bounds, actions: [action] });
      await frame();
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  const click = (event: React.MouseEvent<HTMLImageElement>) => {
    if (!observation?.coordinateInput || !observation.bounds.width || !observation.bounds.height) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.floor((event.clientX - rect.left) * observation.bounds.width / rect.width);
    const y = Math.floor((event.clientY - rect.top) * observation.bounds.height / rect.height);
    void act({ type: event.shiftKey ? 'right_click' : 'click', x: Math.max(0, Math.min(observation.bounds.width - 1, x)), y: Math.max(0, Math.min(observation.bounds.height - 1, y)) });
  };
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-xl font-semibold">Desktop</h2><p className="mt-1 text-sm text-text-secondary">Inspect GUI windows and send approved actions.</p></div>
      <div className="flex gap-2">
        <select aria-label="Desktop machine" className={button} value={machine} onChange={e => setMachine(e.target.value)}>
          {machines.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <button className={button} onClick={() => void refreshWindows()} disabled={busy}><RefreshCw size={16} /></button>
      </div>
    </div>
    {error && <p className="rounded-lg border border-red-400/40 p-3 text-sm text-red-500" role="alert">{error}</p>}
    <div className="grid min-h-64 gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="rounded-xl border border-border-light p-3">
        <h3 className="mb-2 text-sm font-semibold">Windows</h3>
        {windows.length === 0 && <p className="p-2 text-sm text-text-secondary">No windows available</p>}
        {windows.map((item, index) => {
          const id = String(item.window_id || item.id || '');
          return <button key={id || index} className={'mb-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-hover ' + (windowId === id ? 'bg-surface-active-alt' : '')}
            onClick={() => { setWindowId(id); void frame(id); }}>
            <Monitor size={15} className="shrink-0" /><span className="truncate">{asText(item.title || item.name || id)}</span>
          </button>;
        })}
      </aside>
      <section className="min-w-0 overflow-hidden rounded-xl border border-border-light">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light bg-surface-primary-alt px-4 py-3">
          <span className="text-sm font-medium">{windowId || 'Select a window'}</span>
          {windowId && <button className={button} onClick={() => void frame()} disabled={busy}>Refresh frame</button>}
        </div>
        {!image ? <p className="p-10 text-center text-sm text-text-secondary">Select a desktop window to view its latest frame.</p> :
          <div className="flex flex-col items-center gap-3 p-3">
            <img ref={imageRef} src={image} alt="Desktop window frame" className={'max-h-[60vh] max-w-full object-contain ' + (observation?.coordinateInput ? 'cursor-crosshair' : '')} onClick={click} />
            <div className="flex w-full flex-wrap items-center gap-2">
              <label htmlFor="lsm-desktop-keys" className="text-xs text-text-secondary"><Keyboard size={15} className="inline" /> Keyboard</label>
              <input id="lsm-desktop-keys" value={keys} onChange={e => setKeys(e.target.value)}
                placeholder="e.g. CTRL+L" className="min-w-[170px] flex-1 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm" />
              <button className={button} onClick={() => { void act({ type: 'key', keys }); setKeys(''); }} disabled={!keys || busy}>Send key</button>
            </div>
            <p className="self-start text-xs text-text-secondary">{observation?.coordinateInput ? 'Click the image to interact; Shift+click for right click.' : 'This backend does not support coordinate input.'}</p>
          </div>}
      </section>
    </div>
  </div>;
}
