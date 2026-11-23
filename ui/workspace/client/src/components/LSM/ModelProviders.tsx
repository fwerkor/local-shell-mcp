import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { apiBaseUrl, request, QueryKeys } from 'librechat-data-provider';

type Kind = 'openai' | 'anthropic' | 'google';
type Source = 'default' | 'environment' | 'saved' | 'named';
type Profile = {
  name?: string;
  provider: Kind;
  base_url: string;
  models: string[];
  configured: boolean;
  source: Source;
};
type Profiles = { providers: Profile[] };
type Draft = { name: string; provider: Kind; base: string; models: string; apiKey: string };
type Editor = { original: Profile | null };
const input = 'w-full rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary';
const button = 'rounded-lg border border-border-medium px-3 py-2 text-sm text-text-primary hover:bg-surface-secondary disabled:opacity-40';
const kinds: { value: Kind; label: string; defaultUrl: string }[] = [
  { value: 'openai', label: 'OpenAI-compatible', defaultUrl: 'https://api.openai.com/v1' },
  { value: 'anthropic', label: 'Anthropic native', defaultUrl: 'https://api.anthropic.com/v1' },
  { value: 'google', label: 'Google Gemini native', defaultUrl: 'https://generativelanguage.googleapis.com/v1beta' },
];
const protocolLabel = (provider: Kind) => kinds.find((kind) => kind.value === provider)?.label ?? provider;
const channelLabel = (profile: Profile) => profile.name ?? protocolLabel(profile.provider) + ' (legacy)';
const channelId = (profile: Profile) => profile.name ?? 'legacy:' + profile.provider;
const newDraft = (): Draft => ({ name: '', provider: 'openai', base: kinds[0].defaultUrl, models: '', apiKey: '' });
const errorMessage = (reason: unknown) => {
  const error = reason as { response?: { data?: { detail?: string } }; message?: string };
  return error?.response?.data?.detail || error?.message || String(reason);
};

/** Channel instances are distinct from provider protocols; defaults aren't saved channels. */
export default function ModelProviders() {
  const client = useQueryClient();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [draft, setDraft] = useState<Draft>(newDraft);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const url = apiBaseUrl() + '/api/lsm/providers';
  const channels = profiles.filter((profile) => profile.source !== 'default');

  useEffect(() => {
    let live = true;
    request.get<Profiles>(url).then((data) => {
      if (live) setProfiles(data.providers);
    }).catch((reason) => {
      if (live) setError(errorMessage(reason));
    }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [url]);

  const refresh = async () => {
    const data = await request.get<Profiles>(url);
    setProfiles(data.providers);
    await Promise.all([QueryKeys.models, QueryKeys.endpoints].map((name) =>
      client.invalidateQueries({ queryKey: [name], refetchType: 'all' })));
  };
  const beginAdd = () => {
    setEditor({ original: null });
    setDraft(newDraft());
    setConfirmDelete(null);
    setError('');
    setSaved(false);
  };
  const beginEdit = (profile: Profile) => {
    setEditor({ original: profile });
    setDraft({
      name: profile.name ?? '',
      provider: profile.provider,
      base: profile.base_url,
      models: profile.models.join('\n'),
      apiKey: '',
    });
    setConfirmDelete(null);
    setError('');
    setSaved(false);
  };
  const save = async () => {
    if (!editor) return;
    setBusy(true);
    setError('');
    setSaved(false);
    try {
      const original = editor.original;
      const name = draft.name.trim();
      if ((!original || original.name) && !name) throw new Error('Channel name is required');
      const models = draft.models.split(/[\n,]/).map((model) => model.trim()).filter(Boolean);
      if (!models.length) throw new Error('At least one model identifier is required');
      await request.put(url, {
        provider: draft.provider,
        base_url: draft.base.trim(),
        models,
        ...(original?.name || !original ? { name } : {}),
        ...(original?.name && name !== original.name ? { previous_name: original.name } : {}),
        ...(draft.apiKey ? { api_key: draft.apiKey } : {}),
      });
      await refresh();
      setEditor(null);
      setSaved(true);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const remove = async (profile: Profile) => {
    setBusy(true);
    setError('');
    setSaved(false);
    try {
      const query = profile.name
        ? 'name=' + encodeURIComponent(profile.name)
        : 'legacy_provider=' + encodeURIComponent(profile.provider);
      await request.delete(url + '?' + query);
      await refresh();
      setConfirmDelete(null);
      setEditor(null);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return <section id="models" aria-labelledby="model-settings-title" className="space-y-4 rounded-xl border border-border-light p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1">
        <h2 id="model-settings-title" className="text-lg font-semibold">Channels &amp; models / 渠道与模型</h2>
        <p className="text-sm text-text-secondary">Each channel has its own name, protocol, endpoint, credentials and models.</p>
      </div>
      <button type="button" disabled={busy} onClick={beginAdd} className={button}>Add channel</button>
    </div>
    {error && <p role="alert" className="text-sm text-status-error">{error}</p>}
    {saved && <p role="status" className="text-sm text-text-primary">Channel saved. <Link className="underline" to="/c/new">Start a new chat and select a model</Link></p>}
    {loading ? <p className="text-sm text-text-secondary">Loading channels…</p> : (
      channels.length ? <ul aria-label="Configured channels" className="divide-y divide-border-light rounded-lg border border-border-light">
        {channels.map((profile) => <li key={channelId(profile)} className="flex flex-wrap items-center justify-between gap-3 p-3">
          <div className="min-w-0 flex-1">
            <p className="break-words font-medium text-text-primary">{channelLabel(profile)}</p>
            <p className="text-xs text-text-secondary">{protocolLabel(profile.provider)} · {profile.models.length} model{profile.models.length === 1 ? '' : 's'}
              {profile.source === 'environment' ? ' · Environment-configured' : ''}
              {profile.source === 'saved' ? ' · Legacy configuration' : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={button} disabled={busy} onClick={() => beginEdit(profile)} aria-label={'Edit ' + channelLabel(profile)}>Edit</button>
            {profile.source !== 'environment' && (
              confirmDelete === channelId(profile) ? <>
                <button type="button" className={button + ' text-status-error'} disabled={busy} onClick={() => void remove(profile)} aria-label={'Confirm delete ' + channelLabel(profile)}>Confirm delete</button>
                <button type="button" className={button} disabled={busy} onClick={() => setConfirmDelete(null)}>Cancel</button>
              </> : <button type="button" className={button + ' text-status-error'} disabled={busy} onClick={() => { setConfirmDelete(channelId(profile)); setEditor(null); setError(''); }} aria-label={'Delete ' + channelLabel(profile)}>Delete</button>
            )}
          </div>
          {confirmDelete === channelId(profile) && <p className="w-full text-xs text-text-secondary">
            {profile.name ? 'Delete this channel and its saved credentials?' : 'Remove this legacy configuration? Built-in defaults will remain for compatibility.'}
            {' '}Channels used by saved conversations or Agents cannot be deleted.
          </p>}
        </li>)}
      </ul> : <p className="rounded-lg border border-dashed border-border-medium p-5 text-sm text-text-secondary">No channels added yet. Select “Add channel” to configure your first model endpoint.</p>
    )}
    {editor && <form aria-label="Channel configuration" className="space-y-4 rounded-lg border border-border-medium bg-surface-secondary p-4" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <h3 className="font-semibold text-text-primary">{editor.original ? 'Edit ' + channelLabel(editor.original) : 'Add channel'}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        {(!editor.original || editor.original.name) && <label className="space-y-1 text-sm text-text-primary"><span>Channel name</span>
          <input aria-label="Channel name" className={input} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="Research Gateway" maxLength={64} required />
        </label>}
        <label className="space-y-1 text-sm text-text-primary"><span>Provider protocol</span>
          <select aria-label="Model provider" className={input} value={draft.provider} disabled={Boolean(editor.original)} onChange={(event) => {
            const provider = event.target.value as Kind;
            setDraft({ ...draft, provider, base: kinds.find((kind) => kind.value === provider)?.defaultUrl ?? '' });
          }}>
            {kinds.map((kind) => <option key={kind.value} value={kind.value}>{kind.label}</option>)}
          </select>
        </label>
        <label className="space-y-1 text-sm text-text-primary"><span>API base URL</span>
          <input aria-label="Model API base URL" className={input} value={draft.base} onChange={(event) => setDraft({ ...draft, base: event.target.value })} required />
        </label>
        <label className="space-y-1 text-sm text-text-primary"><span>API key</span>
          <input type="password" autoComplete="new-password" aria-label="Model API key" className={input} value={draft.apiKey} onChange={(event) => setDraft({ ...draft, apiKey: event.target.value })} placeholder={editor.original?.configured ? 'Leave blank to keep current key' : 'Optional for local services'} />
        </label>
        <label className="space-y-1 text-sm text-text-primary sm:col-span-2"><span>Models / 模型 (one per line)</span>
          <textarea aria-label="Model identifiers" className={input} value={draft.models} onChange={(event) => setDraft({ ...draft, models: event.target.value })} rows={3} required />
        </label>
      </div>
      <p className="text-xs text-text-secondary">{editor.original?.name ? 'Renaming a channel in use is restricted to protect Agent and conversation references. ' : ''}Keys are stored on the server and never returned here; an empty key preserves an existing one.</p>
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy || !draft.models.trim()} className={button}>{busy ? 'Saving…' : 'Save model channel'}</button>
        <button type="button" disabled={busy} className={button} onClick={() => { setEditor(null); setError(''); }}>Cancel</button>
      </div>
    </form>}
  </section>;
}
