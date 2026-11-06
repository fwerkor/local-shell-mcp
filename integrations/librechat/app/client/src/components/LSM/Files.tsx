import { useEffect, useRef, useState } from 'react';
import { ChevronRight, Download, File, Folder, FolderPlus, Home, RefreshCw, Trash2, Upload, Save, ArrowLeft, FilePlus2 } from 'lucide-react';
import { useAuthContext } from '~/hooks';
import { asText, binaryRequest, endpoint, formatBytes, qs, read, write, type Entry, type RecordValue } from './api';

type Listing = { machine: string; path: string; parent: string; entries: Entry[]; truncated?: boolean };
type Preview = RecordValue & { content?: string; kind?: string; path?: string };
const control = 'rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm hover:bg-surface-hover disabled:opacity-40';
const joinPath = (path: string, name: string) => {
  const separator = path.includes('\\') && !path.includes('/') ? '\\' : '/';
  return path.replace(/[\\/]$/, '') + separator + name;
};
export default function Files() {
  const { token } = useAuthContext();
  const [machine, setMachine] = useState('local');
  const [machines, setMachines] = useState<string[]>(['local']);
  const [path, setPath] = useState('.');
  const [inputPath, setInputPath] = useState('.');
  const [listing, setListing] = useState<Listing | null>(null);
  const [selected, setSelected] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [editor, setEditor] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void read<{ machines?: RecordValue[] }>('machines').then(data => {
      setMachines(['local', ...(data.machines ?? []).map(row => String(row.machine || row.name || row.id || '')).filter(Boolean).filter(n => n !== 'local')]);
    }).catch(() => {});
  }, []);
  const refresh = async (nextPath = path, nextMachine = machine) => {
    setBusy(true);
    try {
      const data = await read<Listing>('files', { machine: nextMachine, path: nextPath });
      setListing(data); setPath(data.path); setInputPath(data.path);
      setError(''); setSelected(''); setPreview(null); setEditor(null);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  useEffect(() => { void refresh(path, machine); }, [machine]);

  const inspect = async (entry: Entry) => {
    const next = entry.path || joinPath(path, entry.name);
    if (entry.type === 'dir' || entry.is_dir) { await refresh(next); return; }
    setSelected(next); setEditor(null);
    try { setPreview(await read<Preview>('files/preview', { machine, path: next })); setError(''); }
    catch (e) { setError(String(e)); }
  };
  const perform = async (action: string, extra: RecordValue) => {
    setBusy(true);
    try { await write('files/' + action, { machine, ...extra }); await refresh(); }
    catch (e) { setError(String(e)); setBusy(false); }
  };
  const newFile = (type: 'mkdir' | 'touch') => {
    const name = window.prompt(type === 'mkdir' ? 'Folder name' : 'File name');
    if (name && name !== '.' && name !== '..' && !/[\\/]/.test(name)) {
      void perform(type, { path: joinPath(path, name) });
    }
  };
  const upload = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    try {
      const response = await binaryRequest('files/upload' + qs({ machine, path: joinPath(path, file.name) }), token, {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
      });
      const result = await response.json() as { ok: boolean; message?: string };
      if (!result.ok) throw new Error(result.message || 'File upload failed');
      await refresh();
    } catch (e) { setError(String(e)); setBusy(false); }
  };
  const download = async () => {
    try {
      const ticket = await write<{ token?: string; url?: string }>('files/download-ticket', { machine, path: selected });
      const route = ticket.token ? 'files/download/' + encodeURIComponent(ticket.token) :
        String(ticket.url || '').replace(/^\/api\/ui\//, '');
      if (!route.startsWith('files/download/')) throw new Error('Invalid download ticket');
      const res = await binaryRequest(route, token);
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = href; anchor.download = selected.split(/[\\/]/).pop() || 'download';
      anchor.click();
      URL.revokeObjectURL(href);
    } catch (e) { setError(String(e)); }
  };
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-xl font-semibold">Files</h2><p className="text-sm text-text-secondary">Browse and manage local or remote workspaces.</p></div>
      <div className="flex flex-wrap gap-2">
        <button className={control} disabled={busy} onClick={() => newFile('mkdir')}><FolderPlus size={17} aria-label="New folder" /></button>
        <button className={control} disabled={busy} onClick={() => newFile('touch')}><FilePlus2 size={17} aria-label="New file" /></button>
        <button className={control} disabled={busy} onClick={() => uploadRef.current?.click()}><Upload size={17} aria-label="Upload" /></button>
        <button className={control} disabled={busy} onClick={() => void refresh()}><RefreshCw size={17} className={busy ? 'animate-spin' : ''} aria-label="Refresh" /></button>
        <input ref={uploadRef} type="file" className="hidden" aria-label="Choose a file to upload"
          onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ''; }} />
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-xs text-text-secondary" htmlFor="lsm-file-machine">Machine</label>
      <select id="lsm-file-machine" value={machine} onChange={e => {setMachine(e.target.value); setPath('.');}}
        className={control}>{machines.map(m => <option key={m} value={m}>{m}</option>)}</select>
      <form className="flex min-w-[220px] flex-1 gap-2" onSubmit={e => { e.preventDefault(); void refresh(inputPath); }}>
        <input aria-label="Directory path" value={inputPath} onChange={e => setInputPath(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 font-mono text-sm" />
        <button type="submit" className={control}>Go</button>
      </form>
      <button className={control} onClick={() => void refresh(listing?.parent || '.')} disabled={!listing || listing.parent === listing.path}>
        <ArrowLeft size={17} aria-label="Parent directory" />
      </button>
    </div>
    {error && <p role="alert" className="rounded-lg border border-red-400/40 p-3 text-sm text-red-500">{error}</p>}
    <div className="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_minmax(280px,1fr)]">
      <section className="min-h-48 overflow-hidden rounded-xl border border-border-light">
        <div className="border-b border-border-light bg-surface-primary-alt px-4 py-3 text-xs text-text-secondary">
          {listing?.entries?.length ?? 0} entries {listing?.truncated ? '· truncated' : ''}
        </div>
        <div className="max-h-[65vh] overflow-y-auto">
          {!listing && <p className="p-5 text-sm text-text-secondary">Loading directory…</p>}
          {listing?.entries?.map((entry, index) => {
            const entryPath = entry.path || joinPath(path, entry.name);
            const directory = entry.type === 'dir' || entry.is_dir === true;
            return <button key={entryPath + index} className={'flex w-full items-center gap-3 border-b border-border-light px-4 py-3 text-left text-sm hover:bg-surface-hover ' + (selected === entryPath ? 'bg-surface-active-alt' : '')}
              onClick={() => void inspect(entry)}>
              {directory ? <Folder size={18} className="shrink-0 text-blue-500" /> : <File size={18} className="shrink-0 text-text-secondary" />}
              <span className="min-w-0 flex-1 truncate">{entry.name}</span>
              <span className="text-xs text-text-secondary">{directory ? '' : formatBytes(entry.size)}</span>
              {directory && <ChevronRight size={15} className="text-text-secondary" />}
            </button>;
          })}
          {listing?.entries?.length === 0 && <p className="p-6 text-center text-sm text-text-secondary">Empty directory</p>}
        </div>
      </section>
      <section className="min-h-48 overflow-hidden rounded-xl border border-border-light">
        <div className="flex items-center justify-between gap-2 border-b border-border-light bg-surface-primary-alt px-4 py-2">
          <span className="min-w-0 truncate text-sm font-medium">{selected ? selected.split(/[\\/]/).pop() : 'Preview'}</span>
          <div className="flex gap-2">
            {selected && <button className={control} title="Download" onClick={() => void download()}><Download size={16} /></button>}
            {selected && <button className={control} title="Delete file" onClick={() => {
              if (window.confirm('Delete ' + selected + '?')) void perform('delete', { path: selected });
            }}><Trash2 size={16} /></button>}
          </div>
        </div>
        {!selected && <p className="p-6 text-sm text-text-secondary">Select a file to inspect its contents.</p>}
        {selected && preview && <div className="p-4">
          {editor !== null ?
            <><textarea value={editor} onChange={e => setEditor(e.target.value)} aria-label="File editor"
              className="h-72 w-full rounded-lg border border-border-medium bg-surface-primary p-3 font-mono text-xs" />
              <button className={control} onClick={() => void perform('write', { path: selected, content: editor, overwrite: true })}><Save size={15} className="mr-2 inline" />Save</button></> :
            <><pre className="max-h-[52vh] overflow-auto whitespace-pre-wrap break-words font-mono text-xs">{asText(preview.content ?? preview.preview ?? preview.kind)}</pre>
              {typeof preview.content === 'string' && <button className={control + ' mt-3'} onClick={() => setEditor(preview.content ?? '')}>Edit</button>}</>}
        </div>}
      </section>
    </div>
  </div>;
}
