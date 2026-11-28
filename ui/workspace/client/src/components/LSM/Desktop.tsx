import { useEffect, useRef, useState } from 'react';
import { Maximize, RefreshCw } from 'lucide-react';
import useLocalize from '~/hooks/useLocalize';
import { useAuthContext } from '~/hooks';
import { workspaceSocket, type WorkspaceConnection } from './workspaceTransport';
import type { RecordValue } from './api';

type Bounds = { x: number; y: number; width: number; height: number };
type Frame = { type: 'frame'; observation_id: string; bounds: Bounds; ttl_s: number; coordinate_input: boolean; image: boolean; frame_id?: number };
type Observation = Frame & { expires: number };
const toolButton = 'rounded p-1.5 hover:bg-surface-hover disabled:opacity-40';

export default function Desktop({ machine, windowId, connection }: { machine: string; windowId: string; connection: WorkspaceConnection }) {
  const localize = useLocalize();
  const { token } = useAuthContext();
  const container = useRef<HTMLDivElement>(null);
  const socket = useRef<WebSocket | null>(null);
  const observation = useRef<Observation | null>(null);
  const sequence = useRef(0);
  const [image, setImage] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  const [generation, setGeneration] = useState(0);
  const [keys, setKeys] = useState('');
  const [coordinateInput, setCoordinateInput] = useState(false);
  const urlRef = useRef('');
  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let delay = 500;
    let pending: Observation | null = null;
    let latest: Observation | null = null;
    let frameVersion = 0;
    let paintedVersion = -1;
    const clearFrame = () => {
      observation.current = null;
      pending = null;
      latest = null;
      frameVersion++;
      paintedVersion = -1;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = '';
      setImage('');
      setCoordinateInput(false);
    };
    clearFrame();
    const connect = () => {
      if (stopped) return;
      setStatus('connecting');
      const ws = workspaceSocket(connection, token, 'desktop', { machine, window_id: windowId, adaptive: '1' });
      ws.binaryType = 'arraybuffer';
      socket.current = ws;
      ws.onopen = () => { if (!stopped && socket.current === ws) setError(''); };
      ws.onmessage = event => {
        if (stopped || socket.current !== ws) return;
        if (event.data instanceof ArrayBuffer) {
          if (!pending) return;
          const next = URL.createObjectURL(new Blob([event.data], { type: 'image/jpeg' }));
          const version = frameVersion;
          const frameId = pending.frame_id;
          pending = null;
          const acknowledge = () => {
            if (!stopped && socket.current === ws && ws.readyState === WebSocket.OPEN && typeof frameId === 'number') {
              ws.send(JSON.stringify({ type: 'frame-ack', frame_id: frameId }));
            }
          };
          const decoded = new Image();
          decoded.onload = () => {
            if (stopped || socket.current !== ws || version !== frameVersion || !latest) { URL.revokeObjectURL(next); return; }
            if (urlRef.current) URL.revokeObjectURL(urlRef.current);
            urlRef.current = next;
            paintedVersion = version;
            observation.current = latest;
            setImage(next);
            setCoordinateInput(latest.coordinate_input);
            setStatus('connected');
            delay = 500;
            acknowledge();
          };
          decoded.onerror = () => { URL.revokeObjectURL(next); ws.close(); };
          decoded.src = next;
          return;
        }
        if (typeof event.data !== 'string') return;
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'frame') {
            const frame = message as Frame;
            const next = { ...frame, expires: performance.now() + Math.max(0, frame.ttl_s * 1000) };
            latest = next;
            if (frame.image) { frameVersion++; pending = next; observation.current = null; }
            else if (urlRef.current && paintedVersion === frameVersion) { observation.current = next; setCoordinateInput(frame.coordinate_input); }
          } else if (message.type === 'error' || (message.type === 'action-ack' && message.ok === false)) {
            setError(String(message.message || 'Desktop operation failed'));
            if (message.refresh && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'refresh' }));
          }
        } catch (e) { setError(String(e)); }
      };
      ws.onclose = event => {
        if (stopped || socket.current !== ws) return;
        clearFrame();
        setStatus('disconnected');
        if (event.reason) setError(event.reason);
        if (event.code === 4401 || event.code === 4403 || event.code === 1000) return;
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 10000);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      socket.current?.close();
      socket.current = null;
      observation.current = null;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = '';
    };
  }, [machine, windowId, connection.ui_path, connection.auth_mode, token, generation]);
  const send = (action: RecordValue) => {
    const frame = observation.current;
    const ws = socket.current;
    if (ws?.readyState !== WebSocket.OPEN) return;
    if (!frame || frame.expires <= performance.now()) { ws.send(JSON.stringify({ type: 'refresh' })); return; }
    ws.send(JSON.stringify({ type: 'action', request_id: ++sequence.current, observation_id: frame.observation_id, bounds: frame.bounds, action }));
  };
  const click = (event: React.MouseEvent<HTMLImageElement>) => {
    const frame = observation.current;
    if (!frame?.coordinate_input || !frame.bounds.width || !frame.bounds.height) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = Math.max(0, Math.min(frame.bounds.width - 1, Math.floor((event.clientX - rect.left) * frame.bounds.width / rect.width)));
    const y = Math.max(0, Math.min(frame.bounds.height - 1, Math.floor((event.clientY - rect.top) * frame.bounds.height / rect.height)));
    send({ type: event.type === 'contextmenu' || event.shiftKey ? 'right_click' : 'click', x, y });
  };
  return <div ref={container} className="flex h-full min-h-0 flex-col bg-surface-primary">
    <div className="flex shrink-0 items-center gap-2 border-b border-border-light px-2 py-1 text-xs">
      <span className="truncate">{machine} · {localize(status === 'connected' ? 'com_lsm_workspace_connected' : status === 'connecting' ? 'com_lsm_workspace_connecting' : 'com_lsm_workspace_disconnected')}</span>
      <span className="flex-1" />
      <button className={toolButton} aria-label={localize('com_lsm_workspace_reconnect')} title={localize('com_lsm_workspace_reconnect')} onClick={() => { if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'refresh' })); else setGeneration(n => n + 1); }}><RefreshCw size={15}/></button>
      <button className={toolButton} title="Fullscreen" aria-label="Fullscreen" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void container.current?.requestFullscreen(); }}><Maximize size={15}/></button>
    </div>
    {error && <div role="alert" className="shrink-0 px-2 py-1 text-xs text-status-error">{error}</div>}
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black/90 p-1">
      {image ? <img src={image} alt={localize('com_lsm_desktop_window_frame')} draggable={false} className={'max-h-full max-w-full object-contain ' + (coordinateInput ? 'cursor-crosshair' : '')} onClick={click} onContextMenu={e => { e.preventDefault(); click(e); }} /> : <span className="text-sm text-white/70">{localize('com_lsm_workspace_connecting')}</span>}
    </div>
    <form className="flex shrink-0 gap-2 border-t border-border-light p-1" onSubmit={e => { e.preventDefault(); if (keys) { send({ type: 'key', keys }); setKeys(''); } }}>
      <input aria-label={localize('com_lsm_keyboard')} value={keys} onChange={e => setKeys(e.target.value)} placeholder={localize('com_lsm_e_g_ctrl_l')} className="min-w-0 flex-1 rounded border border-border-medium bg-surface-primary px-2 py-1 text-xs" />
      <button className="rounded px-2 text-xs hover:bg-surface-hover disabled:opacity-40" disabled={!keys || status !== 'connected'}>{localize('com_lsm_send_key')}</button>
    </form>
  </div>;
}
