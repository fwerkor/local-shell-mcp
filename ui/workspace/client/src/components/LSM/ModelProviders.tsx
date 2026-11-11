import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { apiBaseUrl, request, QueryKeys } from 'librechat-data-provider';

type Profile = { provider: string; base_url?: string; models: string[]; configured?: boolean };
type Profiles = { providers: Profile[] };
const input = 'w-full rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary';

/** Server-managed model channels; original endpoint/model selectors consume the resulting inventory. */
export default function ModelProviders() {
  const client = useQueryClient();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [provider, setProvider] = useState('openai');
  const [base, setBase] = useState('');
  const [models, setModels] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const url = `${apiBaseUrl()}/api/lsm/providers`;
  useEffect(() => {
    let live = true;
    request.get<Profiles>(url).then((data) => { if (live) setProfiles(data.providers); })
      .catch((reason) => { if (live) setError(String(reason)); });
    return () => { live = false; };
  }, [url]);
  useEffect(() => {
    const profile = profiles.find((item) => item.provider === provider);
    setBase(profile?.base_url ?? '');
    setModels(profile?.models.join('\n') ?? '');
    setKey('');
  }, [provider, profiles]);
  const save = async () => {
    setBusy(true); setError(''); setSaved(false);
    try {
      await request.put(url, { provider, base_url: base.trim(),
        models: models.split(/[\n,]/).map((item) => item.trim()).filter(Boolean),
        ...(key ? { api_key: key } : {}) });
      setKey('');
      const data = await request.get<Profiles>(url);
      setProfiles(data.providers);
      await Promise.all([QueryKeys.models, QueryKeys.endpoints].map((name) =>
        client.invalidateQueries({ queryKey: [name], refetchType: 'all' })));
      setSaved(true);
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  return <section id="models" aria-labelledby="model-settings-title" className="space-y-4 rounded-xl border border-border-light p-5">
    <h2 id="model-settings-title" className="text-lg font-semibold">Channels &amp; models / 渠道与模型</h2>
    <p className="text-sm text-text-secondary">Configure server-side credentials and models. API keys are never returned to the browser. Existing keys are preserved when left blank.</p>
    {error && <p role="alert" className="text-status-error">{error}</p>}
    {saved && <p role="status">Model channel saved. <Link className="underline" to="/c/new">Start a new chat and select a model</Link></p>}
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="space-y-1 text-sm"><span>Provider / 渠道</span><select aria-label="Model provider" className={input} value={provider} onChange={(event) => { setProvider(event.target.value); setSaved(false); }}>
        <option value="openai">OpenAI-compatible</option><option value="anthropic">Anthropic</option><option value="google">Google Gemini</option>
      </select></label>
      <label className="space-y-1 text-sm"><span>API key</span><input type="password" autoComplete="new-password" aria-label="Model API key" className={input} value={key} onChange={(event) => setKey(event.target.value)} placeholder={profiles.find((p) => p.provider === provider)?.configured ? 'Configured; leave blank to preserve' : 'API key'} /></label>
      {provider === 'openai' && <label className="space-y-1 text-sm"><span>API base URL</span><input aria-label="Model API base URL" className={input} value={base} onChange={(event) => setBase(event.target.value)} placeholder="https://api.openai.com/v1" /></label>}
      <label className="space-y-1 text-sm"><span>Models / 模型 (one per line)</span><textarea aria-label="Model identifiers" className={input} value={models} onChange={(event) => setModels(event.target.value)} rows={3} placeholder="Model identifiers" /></label>
    </div>
    <button type="button" disabled={busy || !models.trim()} onClick={() => void save()} className="rounded-lg border border-border-medium px-4 py-2 text-sm disabled:opacity-40">{busy ? 'Saving…' : 'Save model channel'}</button>
  </section>;
}
