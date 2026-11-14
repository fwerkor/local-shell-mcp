import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { apiBaseUrl, request, QueryKeys } from 'librechat-data-provider';

type Kind = 'openai' | 'anthropic' | 'google';
type Profile = { name?: string; provider: Kind; base_url?: string; models: string[]; configured?: boolean };
type Profiles = { providers: Profile[] };
const input = 'w-full rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary';
const kinds: { value: Kind; label: string }[] = [
  { value: 'openai', label: 'OpenAI-compatible' },
  { value: 'anthropic', label: 'Anthropic native' },
  { value: 'google', label: 'Google Gemini native' },
];
const identity = (profile: Profile) => profile.name ?? profile.provider;

/** Original LibreChat selectors consume the endpoint inventory; secrets never enter React responses. */
export default function ModelProviders() {
  const client = useQueryClient();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selected, setSelected] = useState('openai');
  const [creating, setCreating] = useState(false);
  const [channelName, setChannelName] = useState('');
  const [provider, setProvider] = useState<Kind>('openai');
  const [base, setBase] = useState('');
  const [models, setModels] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const url = `${apiBaseUrl()}/api/lsm/providers`;
  const active = profiles.find((item) => identity(item) === selected);
  useEffect(() => {
    let live = true;
    request.get<Profiles>(url).then((data) => { if (live) setProfiles(data.providers); })
      .catch((reason) => { if (live) setError(String(reason)); });
    return () => { live = false; };
  }, [url]);
  useEffect(() => {
    if (creating) return;
    setProvider(active?.provider ?? 'openai');
    setChannelName(active?.name ?? '');
    setBase(active?.base_url ?? '');
    setModels(active?.models.join('\n') ?? '');
    setKey('');
  }, [active, creating]);
  const invalidate = async () => {
    await Promise.all([QueryKeys.models, QueryKeys.endpoints].map((name) =>
      client.invalidateQueries({ queryKey: [name], refetchType: 'all' })));
  };
  const chooseDefault = (kind: Kind) => {
    setSelected(kind);
    setCreating(false);
    setSaved(false);
    setError('');
  };
  const add = () => {
    setCreating(true);
    setChannelName('');
    setProvider('openai');
    setBase('https://api.openai.com/v1');
    setModels('');
    setKey('');
    setError('');
    setSaved(false);
  };
  const save = async () => {
    setBusy(true); setError(''); setSaved(false);
    try {
      if (creating && !channelName.trim()) throw new Error('A channel name is required');
      const name = creating ? channelName.trim() : active?.name;
      await request.put(url, { provider, base_url: base.trim(),
        models: models.split(/[\n,]/).map((item) => item.trim()).filter(Boolean),
        ...(name ? { name } : {}),
        ...(key ? { api_key: key } : {}) });
      setKey('');
      const data = await request.get<Profiles>(url);
      setProfiles(data.providers);
      setCreating(false);
      setSelected(name ?? provider);
      await invalidate();
      setSaved(true);
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!active?.name) return;
    setBusy(true); setError(''); setSaved(false);
    try {
      await request.delete(`${url}?name=${encodeURIComponent(active.name)}`);
      const data = await request.get<Profiles>(url);
      setProfiles(data.providers);
      setSelected(provider);
      await invalidate();
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  return <section id="models" aria-labelledby="model-settings-title" className="space-y-4 rounded-xl border border-border-light p-5">
    <h2 id="model-settings-title" className="text-lg font-semibold">Channels &amp; models / 渠道与模型</h2>
    <p className="text-sm text-text-secondary">Configure independent named channels with separate endpoints, API keys, and model catalogs. Existing keys are preserved when left blank; secrets are never returned to the browser.</p>
    {error && <p role="alert" className="text-status-error">{error}</p>}
    {saved && <p role="status">Model channel saved. <Link className="underline" to="/c/new">Start a new chat and select a model</Link></p>}
    <div className="flex flex-wrap items-end gap-3">
      <label className="min-w-52 flex-1 space-y-1 text-sm"><span>Channel</span>
        <select aria-label="Model channel" className={input} value={creating ? '__new__' : selected} onChange={(event) => {
          if (event.target.value === '__new__') add();
          else { setSelected(event.target.value); setCreating(false); setSaved(false); setError(''); }
        }}>
          {profiles.map((item) => <option key={identity(item)} value={identity(item)}>{item.name ?? `${item.provider} (default)`}</option>)}
          {creating && <option value="__new__">New named channel</option>}
        </select>
      </label>
      <button type="button" onClick={add} disabled={busy} className="rounded-lg border border-border-medium px-4 py-2 text-sm disabled:opacity-40">Add named channel</button>
    </div>
    <div className="grid gap-4 sm:grid-cols-2">
      {(creating || active?.name) && <label className="space-y-1 text-sm"><span>Channel name</span>
        <input className={input} aria-label="Channel name" value={channelName} onChange={(event) => setChannelName(event.target.value)} disabled={!creating} placeholder="Research Gateway" />
      </label>}
      <label className="space-y-1 text-sm"><span>Provider protocol</span><select aria-label="Model provider" className={input} value={provider} disabled={Boolean(active?.name && !creating)}
        onChange={(event) => { const kind = event.target.value as Kind; if (creating) setProvider(kind); else chooseDefault(kind); }}>
        {kinds.map((kind) => <option key={kind.value} value={kind.value}>{kind.label}</option>)}
      </select></label>
      <label className="space-y-1 text-sm"><span>API key</span><input type="password" autoComplete="new-password" aria-label="Model API key" className={input} value={key} onChange={(event) => setKey(event.target.value)} placeholder={active?.configured && !creating ? 'Configured; leave blank to preserve' : 'API key'} /></label>
      <label className="space-y-1 text-sm"><span>API base URL</span><input aria-label="Model API base URL" className={input} value={base} onChange={(event) => setBase(event.target.value)} placeholder="https://api.openai.com/v1" /></label>
      <label className="space-y-1 text-sm sm:col-span-2"><span>Models / 模型 (one per line)</span><textarea aria-label="Model identifiers" className={input} value={models} onChange={(event) => setModels(event.target.value)} rows={3} placeholder="Model identifiers" /></label>
    </div>
    <div className="flex flex-wrap gap-3">
      <button type="button" disabled={busy || !models.trim()} onClick={() => void save()} className="rounded-lg border border-border-medium px-4 py-2 text-sm disabled:opacity-40">{busy ? 'Saving…' : 'Save model channel'}</button>
      {creating && <button type="button" disabled={busy} onClick={() => chooseDefault('openai')} className="rounded-lg border border-border-medium px-4 py-2 text-sm">Cancel</button>}
      {active?.name && !creating && <button type="button" disabled={busy} onClick={() => void remove()} className="rounded-lg border border-border-medium px-4 py-2 text-sm text-status-error disabled:opacity-40">Delete named channel</button>}
    </div>
  </section>;
}
