import useLocalize from '~/hooks/useLocalize';
import { useEffect, useRef, useState } from 'react';
import { ChevronRight, Download, File, Folder, FolderPlus, Home, RefreshCw, Trash2, Upload, Save, ArrowLeft, FilePlus2 } from 'lucide-react';
import { useAuthContext } from '~/hooks';
import { asText, binaryRequest, formatBytes, qs, type Entry, type RecordValue } from './api';
import { useControllerServices } from './hooks';

type Listing = { machine: string; path: string; parent: string; entries: Entry[]; truncated?: boolean };
type Preview = RecordValue & { content?: string; kind?: string; path?: string; sha256?: string };
type EditSession = { machine: string; path: string; content: string; sha256: string };
const control = 'rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm hover:bg-surface-hover disabled:opacity-40';
const joinPath = (path: string, name: string) => {
  const separator = path.includes('\\') && !path.includes('/') ? '\\' : '/';
  return path.replace(/[\\/]$/, '') + separator + name;
};
export default function Files() {
  const localize = useLocalize();
  const { read, write } = useControllerServices();
  const { token } = useAuthContext();
  const [machine, setMachine] = useState('local');
  const [machines, setMachines] = useState<string[]>(['local']);
  const [path, setPath] = useState('.');
  const [inputPath, setInputPath] = useState('.');
  const [listing, setListing] = useState<Listing | null>(null);
  const [selected, setSelected] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [editor, setEditor] = useState<EditSession | null>(null);
  const [editorLoading, setEditorLoading] = useState(false);
  const requestVersion = useRef(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void read<{ machines?: RecordValue[] }>('machines').then(data => {
      setMachines(['local', ...(data.machines ?? []).map(row => String(row.machine || row.name || row.id || '')).filter(Boolean).filter(n => n !== 'local')]);
    }).catch(() => {});
  }, []);
  const refresh = async (nextPath = path, nextMachine = machine) => {
    const version = ++requestVersion.current;
    setSelected(''); setPreview(null); setEditor(null); setEditorLoading(false); setListing(null);
    setBusy(true);
    try {
      const data = await read<Listing>('files', { machine: nextMachine, path: nextPath });
      if (requestVersion.current !== version) return;
      setListing(data); setPath(data.path); setInputPath(data.path);
      setError('');
    } catch (e) { if (requestVersion.current === version) setError(String(e)); }
    finally { if (requestVersion.current === version) setBusy(false); }
  };
  useEffect(() => { void refresh(path, machine); }, [machine]);

  const inspect = async (entry: Entry) => {
    const next = entry.path || joinPath(path, entry.name);
    if (entry.type === 'dir' || entry.is_dir) { await refresh(next); return; }
    const version = ++requestVersion.current;
    const selectedMachine = machine;
    setSelected(next); setPreview(null); setEditor(null); setEditorLoading(false);
    try {
      const result = await read<Preview>('files/preview', { machine: selectedMachine, path: next });
      if (requestVersion.current !== version) return;
      setPreview(result); setError('');
    } catch (e) { if (requestVersion.current === version) setError(String(e)); }
  };
  const beginEdit = async () => {
    if (!selected || preview?.kind !== 'text') return;
    const version = requestVersion.current;
    const selectedMachine = machine;
    const selectedPath = selected;
    setEditorLoading(true);
    try {
      const full = await read<Preview>('files/content', { machine: selectedMachine, path: selectedPath });
      if (requestVersion.current !== version) return;
      if (full.kind !== 'text' || full.truncated || typeof full.content !== 'string' ||
          typeof full.sha256 !== 'string' || !/^[a-f0-9]{64}$/i.test(full.sha256)) {
        throw new Error(localize('com_lsm_file_cannot_be_safely_loaded_for_editing'));
      }
      setEditor({ machine: selectedMachine, path: selectedPath, content: full.content, sha256: full.sha256 });
      setError('');
    } catch (e) { if (requestVersion.current === version) setError(String(e)); }
    finally { if (requestVersion.current === version) setEditorLoading(false); }
  };
  const saveEdit = async () => {
    if (!editor || editor.machine !== machine || editor.path !== selected) return;
    await perform('write', {
      machine: editor.machine, path: editor.path, content: editor.content,
      overwrite: true, expected_sha256: editor.sha256,
    });
  };
  const perform = async (action: string, extra: RecordValue) => {
    setBusy(true);
    try { await write('files/' + action, { machine, ...extra }); await refresh(); }
    catch (e) { setError(String(e)); setBusy(false); }
  };
  const newFile = (type: 'mkdir' | 'touch') => {
    const name = window.prompt(type === 'mkdir' ? localize('com_lsm_folder_name') : localize('com_lsm_file_name'));
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
      if (!result.ok) throw new Error(result.message || localize('com_lsm_file_upload_failed'));
      await refresh();
    } catch (e) { setError(String(e)); setBusy(false); }
  };
  const download = async () => {
    try {
      const ticket = await write<{ token?: string; url?: string }>('files/download-ticket', { machine, path: selected });
      const route = ticket.token ? 'files/download/' + encodeURIComponent(ticket.token) :
        String(ticket.url || '').replace(/^\/api\/ui\//, '');
      if (!route.startsWith('files/download/')) throw new Error(localize('com_lsm_invalid_download_ticket'));
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
      <div><h2 className="text-xl font-semibold">{localize('com_lsm_files')}</h2><p className="text-sm text-text-secondary">{localize('com_lsm_browse_and_manage_local_or_remote_workspaces')}</p></div>
      <div className="flex flex-wrap gap-2">
        <button className={control} disabled={busy} onClick={() => newFile('mkdir')}><FolderPlus size={17} aria-label={localize('com_lsm_new_folder')} /></button>
        <button className={control} disabled={busy} onClick={() => newFile('touch')}><FilePlus2 size={17} aria-label={localize('com_lsm_new_file')} /></button>
        <button className={control} disabled={busy} onClick={() => uploadRef.current?.click()}><Upload size={17} aria-label={localize('com_lsm_upload')} /></button>
        <button className={control} disabled={busy} onClick={() => void refresh()}><RefreshCw size={17} className={busy ? 'animate-spin' : ''} aria-label={localize('com_lsm_refresh')} /></button>
        <input ref={uploadRef} type="file" className="hidden" aria-label={localize('com_lsm_choose_a_file_to_upload')}
          onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ''; }} />
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-xs text-text-secondary" htmlFor="lsm-file-machine">{localize('com_lsm_machine')}</label>
      <select id="lsm-file-machine" value={machine} onChange={e => { ++requestVersion.current; setSelected(''); setPreview(null); setEditor(null); setEditorLoading(false); setListing(null); setMachine(e.target.value); setPath('.'); }}
        className={control}>{machines.map(m => <option key={m} value={m}>{m}</option>)}</select>
      <form className="flex min-w-[220px] flex-1 gap-2" onSubmit={e => { e.preventDefault(); void refresh(inputPath); }}>
        <input aria-label={localize('com_lsm_directory_path')} value={inputPath} onChange={e => setInputPath(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 font-mono text-sm" />
        <button type="submit" className={control}>{localize('com_lsm_go')}</button>
      </form>
      <button className={control} onClick={() => void refresh(listing?.parent || '.')} disabled={!listing || listing.parent === listing.path}>
        <ArrowLeft size={17} aria-label={localize('com_lsm_parent_directory')} />
      </button>
    </div>
    {error && <p role="alert" className="rounded-lg border border-status-error-border bg-status-error-subtle p-3 text-sm text-status-error">{error}</p>}
    <div className="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_minmax(280px,1fr)]">
      <section className="min-h-48 overflow-hidden rounded-xl border border-border-light">
        <div className="border-b border-border-light bg-surface-primary-alt px-4 py-3 text-xs text-text-secondary">
          {listing?.entries?.length ?? 0} {localize('com_lsm_entries')} {listing?.truncated ? '· ' + localize('com_lsm_truncated') : ''}
        </div>
        <div className="max-h-[65vh] overflow-y-auto">
          {!listing && <p className="p-5 text-sm text-text-secondary">{localize('com_lsm_loading_directory')}</p>}
          {listing?.entries?.map((entry, index) => {
            const entryPath = entry.path || joinPath(path, entry.name);
            const directory = entry.type === 'dir' || entry.is_dir === true;
            return <button key={entryPath + index} className={'flex w-full items-center gap-3 border-b border-border-light px-4 py-3 text-left text-sm hover:bg-surface-hover ' + (selected === entryPath ? 'bg-surface-active-alt' : '')}
              onClick={() => void inspect(entry)}>
              {directory ? <Folder size={18} className="shrink-0 text-status-info" /> : <File size={18} className="shrink-0 text-text-secondary" />}
              <span className="min-w-0 flex-1 truncate">{entry.name}</span>
              <span className="text-xs text-text-secondary">{directory ? '' : formatBytes(entry.size)}</span>
              {directory && <ChevronRight size={15} className="text-text-secondary" />}
            </button>;
          })}
          {listing?.entries?.length === 0 && <p className="p-6 text-center text-sm text-text-secondary">{localize('com_lsm_empty_directory')}</p>}
        </div>
      </section>
      <section className="min-h-48 overflow-hidden rounded-xl border border-border-light">
        <div className="flex items-center justify-between gap-2 border-b border-border-light bg-surface-primary-alt px-4 py-2">
          <span className="min-w-0 truncate text-sm font-medium">{selected ? selected.split(/[\\/]/).pop() : localize('com_lsm_preview')}</span>
          <div className="flex gap-2">
            {selected && <button className={control} title={localize('com_lsm_download')} onClick={() => void download()}><Download size={16} /></button>}
            {selected && <button className={control} title={localize('com_lsm_delete_file')} onClick={() => {
              if (window.confirm(localize('com_lsm_delete') + selected + '?')) void perform('delete', { path: selected });
            }}><Trash2 size={16} /></button>}
          </div>
        </div>
        {!selected && <p className="p-6 text-sm text-text-secondary">{localize('com_lsm_select_a_file_to_inspect_its_contents')}</p>}
        {selected && preview && <div className="p-4">
          {editor !== null && editor.machine === machine && editor.path === selected ?
            <><textarea value={editor.content} onChange={e => setEditor(current => current ? { ...current, content: e.target.value } : null)} aria-label={localize('com_lsm_file_editor')}
              className="h-72 w-full rounded-lg border border-border-medium bg-surface-primary p-3 font-mono text-xs" />
              <button className={control} disabled={busy} onClick={() => void saveEdit()}><Save size={15} className="mr-2 inline" />{localize('com_lsm_save')}</button></> :
            <><pre className="max-h-[52vh] overflow-auto whitespace-pre-wrap break-words font-mono text-xs">{asText(preview.content ?? preview.preview ?? preview.kind)}</pre>
              {preview.kind === 'text' && <button disabled={busy} className={control + ' mt-3'} onClick={() => void beginEdit()}>{localize('com_lsm_edit')}</button>}</>}
        </div>}
      </section>
    </div>
  </div>;
}
