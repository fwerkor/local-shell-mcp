import { useContext, useEffect, useRef, useState, type PointerEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ThemeContext } from '@librechat/client';
import { QueryKeys } from 'librechat-data-provider';
import Editor, { loader } from '@monaco-editor/react';
import { ArrowUp, ChevronDown, ChevronRight, Download, File, FilePlus2, Folder, FolderPlus, Monitor, PanelBottom, PanelLeft, RefreshCw, Save, Trash2, Upload, X } from 'lucide-react';
import useLocalize from '~/hooks/useLocalize';
import { useAuthContext } from '~/hooks';
import { asText, binaryRequest, qs, read, write, type Entry, type MachineRow, type RecordValue } from './api';
import { useControllerQuery } from './hooks';
import Desktop from './Desktop';
import WorkspaceTerminal from './WorkspaceTerminal';
import WorkspaceJobs from './WorkspaceJobs';
import Operations from './Operations';
import type { WorkspaceConnection } from './workspaceTransport';

loader.config({ paths: { vs: '/monaco/vs' } });
const tool = 'rounded p-1.5 hover:bg-surface-hover disabled:opacity-40';
const input = 'min-w-0 rounded border border-border-medium bg-surface-primary px-2 py-1 text-xs';
const panelNames = ['terminals', 'jobs', 'sessions', 'audit', 'remotes'] as const;
type Panel = typeof panelNames[number];
type Listing = { path: string; parent: string; entries: Entry[]; truncated?: boolean };
type Preview = RecordValue & { kind?: string; content?: string; sha256?: string; rgba?: string; width?: number; height?: number };
type FileTab = { kind: 'file'; id: string; machine: string; path: string; title: string; request: number; loading?: boolean; preview?: Preview; content?: string; saved?: string; sha?: string; error?: string; saving?: boolean };
type DesktopTab = { kind: 'desktop'; id: string; machine: string; windowId: string; title: string };
type Tab = FileTab | DesktopTab;
type Bootstrap = WorkspaceConnection & { machines?: { machines?: MachineRow[] } };
const fileId = (machine: string, path: string) => JSON.stringify(['file', machine, path]);
const desktopId = (machine: string, id: string) => JSON.stringify(['desktop', machine, id]);
const basename = (path: string) => path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path;
const join = (path: string, name: string) => path.replace(/[\\/]$/, '') + (path.includes('\\') && !path.includes('/') ? '\\' : '/') + name;
const isDirectory = (entry: Entry) => entry.type === 'dir' || entry.is_dir === true;
const isDirty = (tab: Tab) => tab.kind === 'file' && tab.content !== undefined && tab.content !== tab.saved;
function panelFor(section?: string): Panel { return panelNames.includes(section as Panel) ? section as Panel : 'terminals'; }
function language(path: string) {
  const ext = basename(path).split('.').pop()?.toLowerCase() || '';
  const languages: Record<string, string> = { py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript', json: 'json', jsonc: 'json', md: 'markdown', sh: 'shell', bash: 'shell', zsh: 'shell', ps1: 'powershell', c: 'c', h: 'cpp', cc: 'cpp', cpp: 'cpp', hpp: 'cpp', rs: 'rust', go: 'go', java: 'java', kt: 'kotlin', css: 'css', html: 'html', xml: 'xml', yaml: 'yaml', yml: 'yaml', toml: 'ini', ini: 'ini', sql: 'sql', rb: 'ruby', php: 'php', lua: 'lua', swift: 'swift', dockerfile: 'dockerfile' };
  return languages[ext] || 'plaintext';
}

function DirectoryTree({ machine, path, depth = 0, selected, onSelect, onFile, onMenu }: {
  machine: string; path: string; depth?: number; selected?: string;
  onSelect: (path: string) => void; onFile: (path: string) => void; onMenu: (e: React.MouseEvent, path: string, directory: boolean) => void;
}) {
  const localize = useLocalize();
  const query = useControllerQuery<Listing>('files', { machine, path, include_parent: 'false' });
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const entries = query.data?.entries ?? [];
  return <div role={depth ? 'group' : 'tree'}>
    {query.isLoading && <p className="px-3 py-1 text-xs text-text-secondary">{localize('com_lsm_loading')}</p>}
    {!!query.error && <p role="alert" className="break-all px-3 py-1 text-xs text-status-error">{String(query.error)}</p>}
    {entries.map((entry, index) => {
      const target = entry.path || join(path, entry.name);
      const dir = isDirectory(entry);
      const open = dir && expanded.has(target);
      return <div key={target + ':' + index}>
        <button role="treeitem" aria-expanded={dir ? open : undefined} aria-selected={selected === target} title={target}
          className={'flex w-full items-center gap-1 py-1 pr-2 text-left text-xs hover:bg-surface-hover ' + (selected === target ? 'bg-surface-active-alt' : '')}
          style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => { onSelect(target); if (dir) setExpanded(old => { const next = new Set(old); if (next.has(target)) next.delete(target); else next.add(target); return next; }); else onFile(target); }}
          onContextMenu={e => onMenu(e, target, dir)}>
          {dir ? <>{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}<Folder size={15} className="shrink-0 text-status-info" /></> : <><span className="w-[13px] shrink-0"/><File size={15} className="shrink-0 text-text-secondary" /></>}
          <span className="min-w-0 truncate">{entry.name}</span>
        </button>
        {open && <DirectoryTree key={target} machine={machine} path={target} depth={depth + 1} selected={selected} onSelect={onSelect} onFile={onFile} onMenu={onMenu} />}
      </div>;
    })}
    {query.data?.truncated && <p className="px-3 py-1 text-xs text-text-secondary">{localize('com_lsm_truncated')}</p>}
  </div>;
}
function ImagePreview({ preview }: { preview: Preview }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!ref.current || !preview.rgba || !preview.width || !preview.height) return;
    const raw = Uint8ClampedArray.from(atob(preview.rgba), c => c.charCodeAt(0));
    if (raw.length !== preview.width * preview.height * 4) return;
    ref.current.getContext('2d')?.putImageData(new ImageData(raw, preview.width, preview.height), 0, 0);
  }, [preview]);
  return <div className="flex h-full items-center justify-center overflow-auto p-4"><canvas ref={ref} width={preview.width} height={preview.height} className="max-h-full max-w-full object-contain" /></div>;
}
function FileEditor({ tab, onChange, onSave, onDownload }: { tab: FileTab; onChange: (value: string) => void; onSave: () => void; onDownload: () => void }) {
  const localize = useLocalize();
  const { resolvedMode } = useContext(ThemeContext);
  const save = useRef(onSave); save.current = onSave;
  if (tab.loading) return <p className="p-4 text-sm text-text-secondary">{localize('com_lsm_loading')}</p>;
  return <div className="flex h-full min-h-0 flex-col">
    <div className="flex shrink-0 items-center gap-1 border-b border-border-light px-2 py-1 text-xs">
      <span className="min-w-0 flex-1 truncate text-text-secondary" title={tab.path}>{tab.machine}:{tab.path}</span>
      <button className={tool} title={localize('com_lsm_download')} aria-label={localize('com_lsm_download')} onClick={onDownload}><Download size={15}/></button>
      <button className={tool} disabled={!tab.sha || tab.saving || !isDirty(tab)} title={localize('com_lsm_save')} aria-label={localize('com_lsm_save')} onClick={onSave}><Save size={15}/></button>
    </div>
    {tab.error && <p role="alert" className="shrink-0 break-all px-2 py-1 text-xs text-status-error">{tab.error}</p>}
    <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
      {tab.preview?.kind === 'image' ? <ImagePreview preview={tab.preview}/> : tab.content !== undefined || tab.preview?.kind === 'text' ?
        <Editor height="100%" value={tab.content ?? String(tab.preview?.content ?? '')} language={language(tab.path)} theme={resolvedMode === 'dark' ? 'vs-dark' : 'vs'}
          options={{ automaticLayout: true, readOnly: !tab.sha, minimap: { enabled: true }, scrollBeyondLastLine: false, fontSize: 13, wordWrap: 'off' }}
          onChange={value => { if (tab.sha) onChange(value ?? ''); }}
          onMount={(editor, monaco) => { editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => save.current()); }} /> :
        <pre className="h-full overflow-auto whitespace-pre-wrap break-all p-3 text-xs">{asText(tab.preview?.content ?? tab.preview?.preview ?? tab.preview?.kind ?? '')}</pre>}
    </div>
  </div>;
}

export default function Workspace({ initialSection }: { initialSection?: string }) {
  const localize = useLocalize();
  const { token } = useAuthContext();
  const client = useQueryClient();
  const bootstrap = useControllerQuery<Bootstrap>('bootstrap', {}, { refetchInterval: 15000 });
  const machines = bootstrap.data?.machines?.machines ?? [];
  const machineNames = [...new Set(machines.map(m => String(m.machine || m.name || m.id || '')).filter(Boolean))];
  const [machine, setMachine] = useState('local');
  const [roots, setRoots] = useState<Record<string, string>>({});
  const root = roots[machine] || '.';
  const [rootInput, setRootInput] = useState(root);
  const [selectedPath, setSelectedPath] = useState('');
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [active, setActive] = useState('');
  const [panel, setPanel] = useState<Panel>(panelFor(initialSection));
  const [panelOpen, setPanelOpen] = useState(true);
  const [treeOpen, setTreeOpen] = useState(true);
  const [treeWidth, setTreeWidth] = useState(245);
  const [panelHeight, setPanelHeight] = useState(275);
  const [desktopPicker, setDesktopPicker] = useState(initialSection === 'desktop');
  const [error, setError] = useState('');
  const [menu, setMenu] = useState<{ path: string; directory: boolean; x: number; y: number } | null>(null);
  const sequence = useRef(0);
  const upload = useRef<HTMLInputElement>(null);
  const uploadDir = useRef('.');
  const workbench = useRef<HTMLDivElement>(null);
  const tab = tabs.find(t => t.id === active);
  const windows = useControllerQuery<{ windows?: RecordValue[]; available?: boolean; reason?: string }>('gui/windows', { machine }, { enabled: desktopPicker });
  const listing = useControllerQuery<Listing>('files', { machine, path: root, include_parent: 'false' }, { enabled: treeOpen });
  useEffect(() => { setRootInput(root); setSelectedPath(''); setMenu(null); }, [machine, root]);
  useEffect(() => { setPanel(panelFor(initialSection)); if (initialSection === 'desktop') setDesktopPicker(true); }, [initialSection]);
  useEffect(() => {
    if (machineNames.length && !machineNames.includes(machine)) setMachine(machineNames[0]);
  }, [bootstrap.data, machine]);
  const dirty = tabs.some(isDirty);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [menu]);
  const updateFile = (id: string, patch: Partial<FileTab>, request?: number) => setTabs(old => old.map(t => t.kind === 'file' && t.id === id && (request === undefined || request === t.request) ? { ...t, ...patch } : t));
  const refreshTree = () => client.invalidateQueries({ queryKey: [QueryKeys.lsmController, 'files'] });
  const selectTab = (item: Tab) => { setActive(item.id); setMachine(item.machine); if (item.kind === 'file') setSelectedPath(item.path); };
  const openFile = async (path: string) => {
    const id = fileId(machine, path);
    setActive(id); setSelectedPath(path);
    if (tabs.some(t => t.id === id)) return;
    const request = ++sequence.current;
    const targetMachine = machine;
    setTabs(old => old.some(t => t.id === id) ? old : [...old, { kind: 'file', id, machine: targetMachine, path, title: basename(path), request, loading: true }]);
    try {
      const preview = await read<Preview>('files/preview', { machine: targetMachine, path });
      if (preview.kind === 'text') {
        try {
          const full = await read<Preview>('files/content', { machine: targetMachine, path });
          if (typeof full.content !== 'string' || typeof full.sha256 !== 'string' || !/^[a-f0-9]{64}$/i.test(full.sha256) || full.truncated) throw new Error(localize('com_lsm_file_cannot_be_safely_loaded_for_editing'));
          updateFile(id, { preview, content: full.content, saved: full.content, sha: full.sha256, loading: false }, request);
        } catch (e) { updateFile(id, { preview, loading: false, error: String(e) }, request); }
      } else updateFile(id, { preview, loading: false }, request);
    } catch (e) { updateFile(id, { loading: false, error: String(e) }, request); }
  };
  const openDesktop = (windowId: string, title: string) => {
    const id = desktopId(machine, windowId);
    setTabs(old => old.some(t => t.id === id) ? old : [...old, { kind: 'desktop', id, machine, windowId, title }]);
    setActive(id); setDesktopPicker(false);
  };
  const closeTab = (item: Tab) => {
    if (item.kind === 'file' && (item.saving || (isDirty(item) && !window.confirm(localize('com_lsm_workspace_unsaved'))))) return;
    const index = tabs.findIndex(t => t.id === item.id);
    const next = tabs.filter(t => t.id !== item.id);
    setTabs(next);
    if (active === item.id) { const replacement = next[Math.min(index, next.length - 1)]; if (replacement) selectTab(replacement); else setActive(''); }
  };
  const saveFile = async (item: FileTab) => {
    if (!item.sha || item.content === undefined || item.saving || !isDirty(item)) return;
    updateFile(item.id, { saving: true, error: undefined }, item.request);
    try {
      const result = await write<{ sha256?: string }>('files/write', { machine: item.machine, path: item.path, content: item.content, expected_sha256: item.sha, overwrite: true });
      if (!result.sha256 || !/^[a-f0-9]{64}$/i.test(result.sha256)) throw new Error(localize('com_lsm_workspace_conflict'));
      updateFile(item.id, { saved: item.content, sha: result.sha256, saving: false }, item.request);
      void refreshTree();
    } catch (e) { updateFile(item.id, { saving: false, error: String(e) }, item.request); }
  };
  const downloadFile = async (targetMachine: string, path: string) => {
    try {
      const ticket = await write<{ token?: string; url?: string }>('files/download-ticket', { machine: targetMachine, path });
      const route = ticket.token ? 'files/download/' + encodeURIComponent(ticket.token) : String(ticket.url || '').replace(/^\/api\/ui\//, '');
      if (!route.startsWith('files/download/')) throw new Error(localize('com_lsm_invalid_download_ticket'));
      const response = await binaryRequest(route, token);
      const href = URL.createObjectURL(await response.blob());
      const a = document.createElement('a'); a.href = href; a.download = basename(path); a.click();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    } catch (e) { setError(String(e)); }
  };
  const mutate = async (action: string, args: RecordValue) => {
    setError('');
    try { await write('files/' + action, { machine, ...args }); await refreshTree(); }
    catch (e) { setError(String(e)); }
  };
  const create = (dir: string, folder: boolean) => {
    const name = window.prompt(localize(folder ? 'com_lsm_folder_name' : 'com_lsm_file_name'));
    if (name && name !== '.' && name !== '..' && !/[\\/]/.test(name)) void mutate(folder ? 'mkdir' : 'touch', { path: join(dir, name) });
  };
  const uploadFiles = async (files: FileList | null) => {
    if (!files) return;
    const targetMachine = machine, dir = uploadDir.current;
    try {
      for (const file of Array.from(files)) {
        const res = await binaryRequest('files/upload' + qs({ machine: targetMachine, path: join(dir, file.name) }), token, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
        const payload = await res.json() as { ok: boolean; message?: string };
        if (!payload.ok) throw new Error(payload.message || localize('com_lsm_file_upload_failed'));
      }
      await refreshTree();
    } catch (e) { setError(String(e)); }
  };
  const chooseUpload = (dir: string) => { uploadDir.current = dir; upload.current?.click(); };
  const setRoot = (path: string) => setRoots(old => ({ ...old, [machine]: path || '.' }));
  const showMenu = (e: React.MouseEvent, path: string, directory: boolean) => {
    e.preventDefault(); setSelectedPath(path);
    setMenu({ path, directory, x: Math.min(e.clientX, window.innerWidth - 185), y: Math.min(e.clientY, window.innerHeight - 190) });
  };
  const resizeTree = (e: PointerEvent<HTMLDivElement>) => { if (e.currentTarget.hasPointerCapture(e.pointerId)) { const left = workbench.current?.getBoundingClientRect().left ?? 0; setTreeWidth(Math.max(145, Math.min(550, e.clientX - left))); } };
  const resizePanel = (e: PointerEvent<HTMLDivElement>) => { if (e.currentTarget.hasPointerCapture(e.pointerId)) { const rect = workbench.current?.getBoundingClientRect(); if (rect) setPanelHeight(Math.max(110, Math.min(rect.height * .8, rect.bottom - e.clientY))); } };
  const connection = bootstrap.data;
  const labels = { terminals: 'com_lsm_section_terminals', jobs: 'com_lsm_workspace_jobs', sessions: 'com_lsm_section_sessions', audit: 'com_lsm_section_audit', remotes: 'com_lsm_machines' } as const;
  return <main ref={workbench} className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-surface-primary text-text-primary">
    <header className="flex shrink-0 items-center gap-2 border-b border-border-light px-2 py-1.5">
      <button className={tool} title={localize('com_lsm_workspace_toggle_explorer')} aria-label={localize('com_lsm_workspace_toggle_explorer')} aria-pressed={treeOpen} onClick={() => setTreeOpen(v => !v)}><PanelLeft size={18}/></button>
      <select className={input} aria-label={localize('com_lsm_machine')} value={machine} onChange={e => { setMachine(e.target.value); setDesktopPicker(false); }}>
        {(machineNames.length ? machineNames : ['local']).map(name => <option key={name} value={name}>{name}</option>)}
      </select>
      <div className="relative">
        <button className={tool} title={localize('com_lsm_workspace_open_desktop')} aria-label={localize('com_lsm_workspace_open_desktop')} aria-expanded={desktopPicker} onClick={() => setDesktopPicker(v => !v)}><Monitor size={18}/></button>
        {desktopPicker && <div className="absolute left-0 top-full z-30 mt-1 max-h-72 w-64 overflow-auto rounded border border-border-medium bg-surface-primary p-1 shadow-lg">
          <div className="flex items-center justify-between px-2 py-1 text-xs font-medium"><span>{localize('com_lsm_workspace_select_window')}</span><button className={tool} onClick={() => void windows.refetch()} title={localize('com_lsm_refresh')}><RefreshCw size={14}/></button></div>
          {windows.isLoading && <p className="p-2 text-xs">{localize('com_lsm_loading')}</p>}
          {!!windows.error && <p role="alert" className="p-2 text-xs text-status-error">{String(windows.error)}</p>}
          {windows.data?.available === false && <p className="p-2 text-xs text-text-secondary">{windows.data.reason || localize('com_lsm_desktop_unavailable')}</p>}
          {(windows.data?.windows ?? []).map((w, i) => { const id = String(w.window_id || w.id || ''); const title = String(w.title || w.name || id); return <button key={id || i} disabled={!id} className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-surface-hover" onClick={() => openDesktop(id, title)}><Monitor size={14} className="shrink-0"/><span className="truncate">{title}</span></button>; })}
          {windows.data?.available !== false && windows.data && !windows.data.windows?.length && <p className="p-2 text-xs text-text-secondary">{localize('com_lsm_no_windows_available')}</p>}
        </div>}
      </div>
      <span className="flex-1"/><button className={tool} title={localize('com_lsm_workspace_toggle_panel')} aria-label={localize('com_lsm_workspace_toggle_panel')} aria-pressed={panelOpen} onClick={() => setPanelOpen(v => !v)}><PanelBottom size={18}/></button>
    </header>
    {!!(error || bootstrap.error) && <div role="alert" className="flex shrink-0 items-center gap-2 px-2 py-1 text-xs text-status-error"><span className="min-w-0 flex-1 break-all">{error || String(bootstrap.error)}</span><button className={tool} onClick={() => setError('')}><X size={14}/></button></div>}
    <div className="flex min-h-0 flex-1 overflow-hidden">
      {treeOpen && <>
        <aside className="flex min-h-0 shrink-0 flex-col border-r border-border-light bg-surface-primary-alt" style={{ width: treeWidth, maxWidth: '45%' }}>
          <div className="flex shrink-0 items-center gap-0.5 px-2 py-1"><span className="min-w-0 flex-1 truncate text-xs font-medium uppercase">{localize('com_lsm_workspace_explorer')}</span>
            <button className={tool} title={localize('com_lsm_new_file')} aria-label={localize('com_lsm_new_file')} onClick={() => create(root, false)}><FilePlus2 size={15}/></button>
            <button className={tool} title={localize('com_lsm_new_folder')} aria-label={localize('com_lsm_new_folder')} onClick={() => create(root, true)}><FolderPlus size={15}/></button>
            <button className={tool} title={localize('com_lsm_upload')} aria-label={localize('com_lsm_upload')} onClick={() => chooseUpload(root)}><Upload size={15}/></button>
            <button className={tool} title={localize('com_lsm_refresh')} aria-label={localize('com_lsm_refresh')} onClick={() => void refreshTree()}><RefreshCw size={15}/></button>
            <input type="file" multiple hidden ref={upload} onChange={e => { void uploadFiles(e.target.files); e.target.value = ''; }}/>
          </div>
          <form className="flex shrink-0 items-center gap-1 px-2 pb-2" onSubmit={e => { e.preventDefault(); setRoot(rootInput); }}>
            <button type="button" className={tool} disabled={!listing.data || listing.data.parent === root} title={localize('com_lsm_parent_directory')} onClick={() => setRoot(listing.data?.parent || '.')}><ArrowUp size={15}/></button>
            <input aria-label={localize('com_lsm_directory_path')} className={input + ' w-full font-mono'} value={rootInput} onChange={e => setRootInput(e.target.value)}/>
          </form>
          <div className="min-h-0 flex-1 overflow-auto"><DirectoryTree key={machine + ':' + root} machine={machine} path={root} selected={selectedPath} onSelect={setSelectedPath} onFile={p => void openFile(p)} onMenu={showMenu}/></div>
        </aside>
        <div role="separator" aria-orientation="vertical" tabIndex={0} className="w-1 shrink-0 cursor-col-resize touch-none hover:bg-blue-500/60" onPointerDown={e => e.currentTarget.setPointerCapture(e.pointerId)} onPointerMove={resizeTree} onKeyDown={e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') setTreeWidth(w => Math.max(145, Math.min(550, w + (e.key === 'ArrowLeft' ? -15 : 15)))); }}/>
      </>}
      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        {!!tabs.length && <div role="tablist" className="flex shrink-0 overflow-x-auto border-b border-border-light bg-surface-primary-alt">
          {tabs.map(item => <div key={item.id} className={'flex shrink-0 items-center border-r border-border-light ' + (active === item.id ? 'bg-surface-primary' : '')}>
            <button role="tab" aria-selected={active === item.id} title={item.machine + ':' + (item.kind === 'file' ? item.path : item.title)} className="flex max-w-60 items-center gap-1.5 px-3 py-2 text-xs" onClick={() => selectTab(item)}>{item.kind === 'desktop' ? <Monitor size={14}/> : <File size={14}/>}<span className="truncate">{item.title}</span>{isDirty(item) && <span aria-label="Unsaved">●</span>}</button>
            <button className={tool + ' mr-1'} aria-label={localize('com_ui_close') + ' ' + item.title} onClick={() => closeTab(item)}><X size={13}/></button>
          </div>)}
        </div>}
        <div className="min-h-0 flex-1 overflow-hidden">
          {tab?.kind === 'file' ? <FileEditor key={tab.id} tab={tab} onChange={content => updateFile(tab.id, { content }, tab.request)} onSave={() => void saveFile(tab)} onDownload={() => void downloadFile(tab.machine, tab.path)}/> :
            tab?.kind === 'desktop' && connection ? <Desktop key={tab.id} machine={tab.machine} windowId={tab.windowId} connection={connection}/> :
            <div className="flex h-full items-center justify-center p-4 text-sm text-text-secondary">{localize('com_lsm_workspace_no_file')}</div>}
        </div>
      </section>
    </div>
    {panelOpen && <div role="separator" aria-orientation="horizontal" tabIndex={0} className="h-1 shrink-0 cursor-row-resize touch-none border-t border-border-light hover:bg-blue-500/60" onPointerDown={e => e.currentTarget.setPointerCapture(e.pointerId)} onPointerMove={resizePanel} onKeyDown={e => { if (e.key === 'ArrowUp' || e.key === 'ArrowDown') setPanelHeight(h => Math.max(110, h + (e.key === 'ArrowUp' ? 15 : -15))); }}/>}
    <section className="flex min-h-0 shrink-0 flex-col border-t border-border-light" style={panelOpen ? { height: panelHeight, maxHeight: '80%' } : undefined}>
      <div role="tablist" className="flex shrink-0 items-center overflow-x-auto border-b border-border-light bg-surface-primary-alt">
        {panelNames.map(name => <button key={name} role="tab" aria-selected={panel === name && panelOpen} className={'shrink-0 border-b-2 px-3 py-2 text-xs font-medium uppercase ' + (panel === name && panelOpen ? 'border-text-primary text-text-primary' : 'border-transparent text-text-secondary hover:text-text-primary')} onClick={() => { setPanel(name); setPanelOpen(true); }}>{localize(labels[name])}</button>)}
        <span className="flex-1"/><button className={tool} aria-label={localize('com_lsm_workspace_toggle_panel')} onClick={() => setPanelOpen(v => !v)}><ChevronDown size={15} className={panelOpen ? '' : 'rotate-180'}/></button>
      </div>
      {panelOpen && <div className="min-h-0 flex-1 overflow-auto">
        {panel === 'terminals' && connection ? <WorkspaceTerminal key={machine} machine={machine} cwd={root} connection={connection}/> : panel === 'jobs' ? <WorkspaceJobs key={machine} machine={machine}/> : panel !== 'terminals' ? <div className="p-2"><Operations key={panel} section={panel}/></div> : null}
      </div>}
    </section>
    {menu && <div className="fixed z-50 w-44 rounded border border-border-medium bg-surface-primary p-1 text-xs shadow-lg" style={{ left: menu.x, top: menu.y }} onClick={() => setMenu(null)}>
      {menu.directory ? <><button className="block w-full px-2 py-1.5 text-left hover:bg-surface-hover" onClick={() => setRoot(menu.path)}>{localize('com_lsm_go')}</button><button className="block w-full px-2 py-1.5 text-left hover:bg-surface-hover" onClick={() => create(menu.path, false)}>{localize('com_lsm_new_file')}</button><button className="block w-full px-2 py-1.5 text-left hover:bg-surface-hover" onClick={() => create(menu.path, true)}>{localize('com_lsm_new_folder')}</button><button className="block w-full px-2 py-1.5 text-left hover:bg-surface-hover" onClick={() => chooseUpload(menu.path)}>{localize('com_lsm_upload')}</button></> : <button className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-surface-hover" onClick={() => void downloadFile(machine, menu.path)}><Download size={14}/>{localize('com_lsm_download')}</button>}
      <button className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-status-error hover:bg-surface-hover" onClick={() => { if (window.confirm(localize('com_lsm_delete') + menu.path + '?')) void mutate('delete', { path: menu.path, recursive: menu.directory }); }}><Trash2 size={14}/>{localize('com_lsm_delete_file')}</button>
    </div>}
  </main>;
}
