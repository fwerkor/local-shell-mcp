import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, LockKeyhole, RefreshCw, RotateCcw, Save, Search, Settings2,
} from 'lucide-react';
import useLocalize from '~/hooks/useLocalize';
import ModelProviders from './ModelProviders';
import { useControllerServices } from './hooks';

type SettingField = {
  name: string;
  group: string;
  type: 'boolean' | 'integer' | 'list' | 'text';
  value: unknown;
  configured: boolean;
  sensitive: boolean;
  locked: boolean;
  pending: boolean;
  source: 'environment' | 'config' | 'default';
  choices?: string[] | null;
};
type ConfigSnapshot = {
  path: string;
  revision: string;
  fields: SettingField[];
  running: { port: number; ui_path: string };
};
type DraftValue = string | boolean | null;
type Draft = Record<string, DraftValue>;

const CRITICAL = new Set([
  'host', 'port', 'mode', 'auth_mode', 'ui_enabled', 'ui_path', 'state_dir',
  'state_backend', 'stateless_controller', 'oauth_jwt_secret', 'public_base_url',
]);
const HELP: Record<string, string> = {
  host: 'Address on which the Controller listens',
  port: 'Controller listener port; changing it may require deployment changes',
  ui_path: 'Native WebUI URL prefix',
  auth_mode: 'Disabling authentication may expose the Controller',
  oauth_jwt_secret: 'Changing this secret invalidates existing OAuth grants',
  oauth_admin_pin: 'PIN used to approve OAuth clients',
  hosted_chat_enabled: 'Enable the legacy Hosted Chat fallback',
  workspace_root: 'Local filesystem workspace root',
  state_dir: 'Directory containing Controller state',
  allow_full_container: 'Disable built-in command and path restrictions',
};
const action = 'inline-flex items-center justify-center gap-2 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm font-medium hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40';
const control = 'w-full min-w-0 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary outline-none focus:border-border-heavy disabled:cursor-not-allowed disabled:opacity-55';

function initialValue(field: SettingField): DraftValue {
  if (field.sensitive) return '';
  if (field.type === 'boolean') return field.value === true;
  if (field.type === 'list') return Array.isArray(field.value) ? field.value.join('\n') : '';
  return field.value == null ? '' : String(field.value);
}

function serializeChanges(fields: SettingField[], draft: Draft): Record<string, unknown> {
  const changes: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(draft)) {
    const field = fields.find((item) => item.name === name);
    if (!field || field.locked) throw new Error(`Setting ${name} cannot be edited`);
    if (value === null) { changes[name] = null; continue; }
    if (field.type === 'integer') {
      const raw = String(value).trim();
      const number = Number(raw);
      if (!/^-?\d+$/.test(raw) || !Number.isSafeInteger(number)) {
        throw new Error(`${name}: expected a valid integer`);
      }
      changes[name] = number;
    } else if (field.type === 'list') {
      changes[name] = String(value).split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
    } else if (field.type === 'boolean') {
      changes[name] = value === true;
    } else {
      changes[name] = String(value);
    }
  }
  return changes;
}

function nativeSettingsUrl(): string {
  const entry = document.querySelector<HTMLMetaElement>('meta[name="lsm-ui-entry-url"]')?.content ?? '/ui/#/hosted-chat';
  return entry.split('#')[0] + '#/settings';
}

export default function Settings() {
  const localize = useLocalize();
  const { read, write } = useControllerServices();
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [search, setSearch] = useState('');
  const [group, setGroup] = useState('');
  const [busy, setBusy] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const reload = async (discardEdits = false) => {
    if (Object.keys(draft).length && !discardEdits) return;
    setBusy(true);
    setError('');
    try {
      const next = await read<ConfigSnapshot>('settings/view');
      if (!mounted.current) return;
      setSnapshot(next);
      setDraft({});
    } catch (reason) {
      if (mounted.current) setError(String(reason));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  useEffect(() => { void reload(true); }, []);

  const fields = snapshot?.fields ?? [];
  const groups = useMemo(() => [...new Set(fields.map((field) => field.group))], [snapshot]);
  const filtered = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return fields.filter((field) => (!group || field.group === group) &&
      (!term || `${field.name} ${field.group} ${HELP[field.name] ?? ''}`.toLocaleLowerCase().includes(term)));
  }, [snapshot, search, group]);
  const changed = Object.keys(draft).length;
  const pendingRestart = fields.some((field) => field.pending);
  const hasPermissionError = /(?:admin:config|scope|403|forbidden|permission|unauthori[sz]ed)/i.test(error);

  const update = (field: SettingField, value: DraftValue) => {
    if (field.locked || busy) return;
    setDraft((current) => {
      const next = { ...current };
      if ((field.sensitive && value === '') || (!field.sensitive && value === initialValue(field))) {
        delete next[field.name];
      } else {
        next[field.name] = value;
      }
      return next;
    });
    setNotice('');
  };

  const reset = (field: SettingField) => {
    if (field.locked || busy) return;
    setDraft((current) => {
      const next = { ...current };
      if (field.source === 'config') next[field.name] = null;
      else delete next[field.name];
      return next;
    });
    setNotice('');
  };

  const restart = async () => {
    if (!window.confirm(localize('com_lsm_settings_restart_confirm'))) return;
    setBusy(true);
    setRestarting(true);
    setError('');
    setNotice(localize('com_lsm_settings_restart_requested'));
    try {
      await write('settings/restart', {});
      // LibreChat remains available while the Controller restarts.
      for (let attempt = 0; attempt < 35 && mounted.current; attempt++) {
        await new Promise((resolve) => window.setTimeout(resolve, 1400));
        try {
          const next = await read<ConfigSnapshot>('settings/view');
          if (!mounted.current) return;
          if (attempt < 3) continue;
          setSnapshot(next);
          setDraft({});
          setNotice(localize('com_lsm_settings_restart_done'));
          return;
        } catch { /* A temporary disconnect is expected during restart. */ }
      }
      if (mounted.current) setError(localize('com_lsm_settings_restart_unreachable'));
    } catch (reason) {
      if (mounted.current) setError(String(reason));
    } finally {
      if (mounted.current) { setBusy(false); setRestarting(false); }
    }
  };

  const save = async (restartAfter: boolean) => {
    if (!snapshot || !changed) return;
    let changes: Record<string, unknown>;
    try { changes = serializeChanges(fields, draft); }
    catch (reason) { setError(String(reason)); return; }
    const critical = Object.keys(changes).filter((name) => CRITICAL.has(name));
    if (critical.length && !window.confirm(`${localize('com_lsm_settings_critical_confirm')}\n\n${critical.join(', ')}`)) return;
    if (restartAfter && !window.confirm(localize('com_lsm_settings_restart_confirm'))) return;
    setBusy(true);
    setError('');
    try {
      await write('settings/save', { changes, revision: snapshot.revision });
      const next = await read<ConfigSnapshot>('settings/view');
      if (!mounted.current) return;
      setSnapshot(next);
      setDraft({});
      setNotice(localize('com_lsm_settings_saved'));
      if (restartAfter) {
        setRestarting(true);
        setNotice(localize('com_lsm_settings_restart_requested'));
        await write('settings/restart', {});
        let connected = false;
        for (let attempt = 0; attempt < 35 && mounted.current; attempt++) {
          await new Promise((resolve) => window.setTimeout(resolve, 1400));
          try {
            const current = await read<ConfigSnapshot>('settings/view');
            if (attempt < 3) continue;
            if (mounted.current) {
              setSnapshot(current);
              setNotice(localize('com_lsm_settings_restart_done'));
            }
            connected = true;
            break;
          } catch { /* Retry while the Controller is stopping or starting. */ }
        }
        if (!connected && mounted.current) setError(localize('com_lsm_settings_restart_unreachable'));
      }
    } catch (reason) {
      if (mounted.current) setError(String(reason));
    } finally {
      if (mounted.current) { setBusy(false); setRestarting(false); }
    }
  };

  return <div className="space-y-5">
    <ModelProviders />
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-xl font-semibold"><Settings2 size={21} />{localize('com_lsm_settings_title')}</h2>
        <p className="mt-1 text-sm text-text-secondary">{localize('com_lsm_settings_description')}</p>
        {snapshot && <p className="mt-2 break-all font-mono text-xs text-text-secondary">{snapshot.path}</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={action} disabled={busy || changed > 0} onClick={() => void reload()}>
          <RefreshCw size={15} className={busy ? 'animate-spin' : ''} />{localize('com_lsm_settings_reload')}
        </button>
        <button type="button" className={action} disabled={busy || !changed} onClick={() => void save(false)}>
          <Save size={15} />{localize('com_lsm_settings_save')} {changed > 0 ? `(${changed})` : ''}
        </button>
        <button type="button" className={action + ' bg-surface-active-alt'} disabled={busy || !changed} onClick={() => void save(true)}>
          {localize('com_lsm_settings_save_restart')}
        </button>
        <button type="button" className={action} disabled={busy || changed > 0} onClick={() => void restart()}>
          <RotateCcw size={15} />{localize('com_lsm_settings_restart')}
        </button>
      </div>
    </div>

    {error && <div role="alert" className="space-y-2 rounded-lg border border-status-error-border bg-status-error-subtle p-4 text-sm text-status-error">
      <p>{error}</p>
      {hasPermissionError && <p><a href={nativeSettingsUrl()} className="font-semibold underline">{localize('com_lsm_settings_authorize')}</a></p>}
    </div>}
    {(notice || pendingRestart || changed > 0) && <div role="status" className="flex gap-2 rounded-lg border border-border-light bg-surface-secondary px-4 py-3 text-sm text-text-secondary">
      {restarting ? <RefreshCw size={17} className="shrink-0 animate-spin" /> : pendingRestart ? <AlertTriangle size={17} className="shrink-0" /> : <CheckCircle2 size={17} className="shrink-0" />}
      <span>{notice || (changed ? localize('com_lsm_settings_unsaved') : localize('com_lsm_settings_pending'))}</span>
    </div>}
    <p className="text-xs text-text-secondary">{localize('com_lsm_settings_precedence')}</p>

    {!snapshot && !error && <p className="py-12 text-center text-sm text-text-secondary">{localize('com_lsm_settings_loading')}</p>}
    {snapshot && <>
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[190px] flex-1">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
          <input aria-label={localize('com_lsm_settings_search')} className={control + ' pl-9'} type="search" value={search}
            placeholder={localize('com_lsm_settings_search')} onChange={(event) => setSearch(event.target.value)} />
        </div>
        <select className={control + ' max-w-64'} aria-label={localize('com_lsm_settings_group')}
          value={group} onChange={(event) => setGroup(event.target.value)}>
          <option value="">{localize('com_lsm_settings_all_groups')}</option>
          {groups.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <span className="text-xs text-text-secondary">{filtered.length} / {fields.length}</span>
      </div>

      {groups.filter((item) => !group || item === group).map((item) => {
        const members = filtered.filter((field) => field.group === item);
        if (!members.length) return null;
        return <section key={item} className="overflow-hidden rounded-xl border border-border-light bg-surface-primary">
          <div className="flex items-center justify-between gap-3 border-b border-border-light bg-surface-secondary px-4 py-3">
            <h3 className="text-sm font-semibold">{item}</h3><span className="text-xs text-text-secondary">{members.length}</span>
          </div>
          <div className="divide-y divide-border-light">
            {members.map((field) => {
              const dirty = Object.prototype.hasOwnProperty.call(draft, field.name);
              const resetQueued = dirty && draft[field.name] === null;
              const value = resetQueued ? initialValue(field) : dirty ? draft[field.name] : initialValue(field);
              const meta = field.locked ? localize('com_lsm_settings_environment') : field.source === 'config' ? localize('com_lsm_settings_override') : localize('com_lsm_settings_default');
              return <div key={field.name} className={'grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] sm:items-center sm:gap-6' + (dirty ? ' border-l-[3px] border-l-border-heavy' : '')}>
                <div className="min-w-0 space-y-1">
                  <label htmlFor={'lsm-setting-' + field.name} className="block text-sm font-medium">{field.name.replaceAll('_', ' ')}</label>
                  <code className="break-all text-xs text-text-secondary">{field.name}</code>
                  {HELP[field.name] && <p className="text-xs text-text-secondary">{HELP[field.name]}</p>}
                  <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary">
                    {field.locked && <LockKeyhole size={12} />}
                    <span>{meta}</span>
                    {field.sensitive && <span>· {localize('com_lsm_settings_secret')}</span>}
                    {field.pending && <span>· {localize('com_lsm_settings_pending_short')}</span>}
                    {resetQueued && <span>· {localize('com_lsm_settings_reset_queued')}</span>}
                  </div>
                </div>
                <div className="flex min-w-0 items-start gap-2">
                  {field.type === 'boolean' || field.choices ?
                    <select id={'lsm-setting-' + field.name} className={control} disabled={busy || field.locked || resetQueued}
                      value={field.type === 'boolean' ? String(value === true) : String(value ?? '')}
                      onChange={(event) => update(field, field.type === 'boolean' ? event.target.value === 'true' : event.target.value)}>
                      {(field.type === 'boolean' ? ['true', 'false'] : field.choices ?? []).map((option) =>
                        <option key={option} value={option}>{option === 'true' ? localize('com_lsm_settings_enabled') : option === 'false' ? localize('com_lsm_settings_disabled') : option}</option>)}
                    </select> : field.type === 'list' ?
                      <textarea id={'lsm-setting-' + field.name} className={control} rows={2} disabled={busy || field.locked || resetQueued}
                        value={String(value ?? '')} onChange={(event) => update(field, event.target.value)} /> :
                      <input id={'lsm-setting-' + field.name} className={control}
                        type={field.sensitive ? 'password' : 'text'} inputMode={field.type === 'integer' ? 'numeric' : undefined}
                        autoComplete="off" disabled={busy || field.locked || resetQueued}
                        placeholder={field.sensitive && field.configured ? localize('com_lsm_settings_secret_configured') : undefined}
                        value={String(value ?? '')} onChange={(event) => update(field, event.target.value)} />}
                  {!field.locked && <button type="button" className={action + ' shrink-0'} disabled={busy || (!dirty && field.source !== 'config')}
                    aria-label={localize('com_lsm_settings_reset') + ' ' + field.name} onClick={() => reset(field)}>{localize('com_lsm_settings_reset')}</button>}
                </div>
              </div>;
            })}
          </div>
        </section>;
      })}
      {filtered.length === 0 && <p className="py-12 text-center text-sm text-text-secondary">{localize('com_lsm_settings_no_matches')}</p>}
    </>}
  </div>;
}
