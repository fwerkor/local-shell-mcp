import { useEffect, useState } from 'react';
import useLocalize from '~/hooks/useLocalize';
import type { TranslationKeys } from '~/hooks/useLocalize';
import { useQueryClient } from '@tanstack/react-query';
import { apiBaseUrl, request, QueryKeys } from 'librechat-data-provider';
import SamplingFields, { samplingDraft, parseSampling } from '~/components/Endpoints/SamplingFields';
import type { Sampling, SamplingDraft } from '~/components/Endpoints/SamplingFields';

type Kind = 'openai' | 'anthropic' | 'google';
type Source = 'default' | 'environment' | 'saved' | 'named';
type Profile = {
  name?: string;
  provider: Kind;
  base_url: string;
  models: string[];
  model_contexts?: Record<string, number>;
  model_sampling?: Record<string, Sampling>;
  include_usage?: boolean;
  configured: boolean;
  source: Source;
};
type Profiles = { providers: Profile[] };
type Draft = { name: string; provider: Kind; base: string; models: string;
  contexts: Record<string, string>; sampling: Record<string, SamplingDraft>; includeUsage: boolean; apiKey: string };
type Editor = { original: Profile | null };
const input = 'w-full rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary';
const button = 'rounded-lg border border-border-medium px-3 py-2 text-sm text-text-primary hover:bg-surface-secondary disabled:opacity-40';
const kinds: { value: Kind; label: TranslationKeys; defaultUrl: string }[] = [
  { value: 'openai', label: 'com_lsm_channel_protocol_openai', defaultUrl: 'https://api.openai.com/v1' },
  { value: 'anthropic', label: 'com_lsm_channel_protocol_anthropic', defaultUrl: 'https://api.anthropic.com/v1' },
  { value: 'google', label: 'com_lsm_channel_protocol_google', defaultUrl: 'https://generativelanguage.googleapis.com/v1beta' },
];
const channelId = (profile: Profile) => profile.name ?? 'legacy:' + profile.provider;
const newDraft = (): Draft => ({ name: '', provider: 'openai', base: kinds[0].defaultUrl,
  models: '', contexts: {}, sampling: {}, includeUsage: true, apiKey: '' });
const errorMessage = (reason: unknown) => {
  const error = reason as { response?: { data?: { detail?: string; message?: string } | string }; message?: string };
  const data = error?.response?.data;
  // Starlette may return plain text for HTTPException rather than JSON.
  if (typeof data === 'string' && data.trim() && !data.trim().startsWith('<') && data.length <= 512) {
    return data.trim();
  }
  return (typeof data === 'object' ? (data?.detail || data?.message) : undefined) || error?.message || String(reason);
};

/** Channel instances are distinct from provider protocols; defaults aren't saved channels. */
export default function ModelProviders() {
  const localize = useLocalize();
  const protocolLabel = (provider: Kind) => {
    const key = kinds.find((kind) => kind.value === provider)?.label;
    return key ? localize(key) : provider;
  };
  const channelLabel = (profile: Profile) => profile.name ?? localize('com_lsm_channel_legacy_name', { protocol: protocolLabel(profile.provider) });
  const client = useQueryClient();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [draft, setDraft] = useState<Draft>(newDraft);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [forceDelete, setForceDelete] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const url = apiBaseUrl() + '/api/lsm/providers';
  const channels = profiles.filter((profile) => profile.source !== 'default');
  const draftModels = [...new Set(draft.models.split(/[\n,]/).map((model) => model.trim()).filter(Boolean))];

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
    await Promise.all([QueryKeys.models, QueryKeys.endpoints, QueryKeys.tokenConfig].map((name) =>
      client.invalidateQueries({ queryKey: [name], refetchType: 'all' })));
  };
  const beginAdd = () => {
    setEditor({ original: null });
    setDraft(newDraft());
    setConfirmDelete(null);
    setForceDelete(null);
    setError('');
    setSuccess('');
  };
  const beginEdit = (profile: Profile) => {
    setEditor({ original: profile });
    setDraft({
      name: profile.name ?? '',
      provider: profile.provider,
      base: profile.base_url,
      models: profile.models.join('\n'),
      contexts: Object.fromEntries(Object.entries(profile.model_contexts ?? {}).map(([key, value]) => [key, String(value)])),
      sampling: Object.fromEntries(Object.entries(profile.model_sampling ?? {}).map(([model, value]) => [model, samplingDraft(value)])),
      includeUsage: profile.include_usage !== false,
      apiKey: '',
    });
    setConfirmDelete(null);
    setForceDelete(null);
    setError('');
    setSuccess('');
  };
  const save = async () => {
    if (!editor) return;
    setBusy(true);
    setError('');
    setSuccess('');
    try {
      const original = editor.original;
      const name = draft.name.trim();
      if ((!original || original.name) && !name) throw new Error(localize('com_lsm_channel_name_required'));
      const models = draftModels;
      const modelContexts: Record<string, number> = {};
      for (const model of models) {
        const raw = draft.contexts[model]?.trim();
        if (!raw) continue;
        const tokens = Number(raw);
        if (!Number.isInteger(tokens) || tokens < 1 || tokens > 2_000_000) {
          throw new Error(localize('com_lsm_channel_context_invalid'));
        }
        modelContexts[model] = tokens;
      }
      if (!models.length) throw new Error(localize('com_lsm_channel_models_required'));
      const modelSampling = Object.fromEntries(models
        .map((model) => [model, parseSampling(draft.sampling[model] ?? samplingDraft(), draft.provider)] as const)
        .filter(([, value]) => Object.keys(value).length > 0));
      await request.put(url, {
        provider: draft.provider,
        base_url: draft.base.trim(),
        models,
        model_contexts: modelContexts,
        model_sampling: modelSampling,
        ...(draft.provider === 'openai' ? { include_usage: draft.includeUsage } : {}),
        ...(original?.name || !original ? { name } : {}),
        ...(original?.name && name !== original.name ? { previous_name: original.name } : {}),
        ...(draft.apiKey ? { api_key: draft.apiKey } : {}),
      });
      await refresh();
      setEditor(null);
      setSuccess(localize('com_lsm_channel_saved'));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  const remove = async (profile: Profile, force = false) => {
    setBusy(true);
    setError('');
    setSuccess('');
    try {
      const query = profile.name
        ? 'name=' + encodeURIComponent(profile.name)
        : 'legacy_provider=' + encodeURIComponent(profile.provider);
      await request.delete(url + '?' + query + (force ? '&force=true' : ''));
      await refresh();
      setConfirmDelete(null);
      setForceDelete(null);
      setEditor(null);
      setSuccess(localize('com_lsm_channel_deleted'));
    } catch (reason) {
      const response = (reason as { response?: { status?: number; data?: { can_force?: boolean } } })?.response;
      if (response?.status === 409 && response.data?.can_force === true && profile.name) {
        setForceDelete(channelId(profile));
      }
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1">
        
        <p className="text-sm text-text-secondary">{localize('com_lsm_channel_description')}</p>
      </div>
      <button type="button" disabled={busy} onClick={beginAdd} className={button}>{localize('com_lsm_channel_add')}</button>
    </div>
    {error && <p role="alert" className="text-sm text-status-error">{error}</p>}
    {success && <p role="status" className="text-sm text-text-primary">{success}</p>}
    {loading ? <p className="text-sm text-text-secondary">{localize('com_lsm_channel_loading')}</p> : (
      channels.length ? <ul aria-label={localize('com_lsm_channel_configured')} className="divide-y divide-border-light rounded-lg border border-border-light">
        {channels.map((profile) => <li key={channelId(profile)} className="flex flex-wrap items-center justify-between gap-3 p-3">
          <div className="min-w-0 flex-1">
            <p className="break-words font-medium text-text-primary">{channelLabel(profile)}</p>
            <p className="text-xs text-text-secondary">{protocolLabel(profile.provider)} · {localize('com_lsm_channel_model_count', { count: profile.models.length })}
              {profile.source === 'environment' ? localize('com_lsm_channel_environment') : ''}
              {profile.source === 'saved' ? localize('com_lsm_channel_legacy') : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={button} disabled={busy} onClick={() => beginEdit(profile)} aria-label={localize('com_lsm_channel_edit_name', { name: channelLabel(profile) })}>{localize('com_ui_edit')}</button>
            {profile.source !== 'environment' && (
              confirmDelete === channelId(profile) ? <>
                {forceDelete === channelId(profile)
                  ? <button type="button" className={button + ' text-status-error'} disabled={busy} onClick={() => void remove(profile, true)} aria-label={localize('com_lsm_channel_delete_anyway_name', { name: channelLabel(profile) })}>{localize('com_lsm_channel_delete_anyway')}</button>
                  : <button type="button" className={button + ' text-status-error'} disabled={busy} onClick={() => void remove(profile)} aria-label={localize('com_lsm_channel_confirm_delete_name', { name: channelLabel(profile) })}>{localize('com_lsm_channel_confirm_delete')}</button>}
                <button type="button" className={button} disabled={busy} onClick={() => { setConfirmDelete(null); setForceDelete(null); setError(''); }}>{localize('com_ui_cancel')}</button>
              </> : <button type="button" className={button + ' text-status-error'} disabled={busy} onClick={() => { setConfirmDelete(channelId(profile)); setForceDelete(null); setEditor(null); setError(''); }} aria-label={localize('com_lsm_channel_delete_name', { name: channelLabel(profile) })}>{localize('com_ui_delete')}</button>
            )}
          </div>
          {confirmDelete === channelId(profile) && <p className="w-full text-xs text-text-secondary">
            {profile.name ? localize('com_lsm_channel_delete_confirm') : localize('com_lsm_channel_delete_legacy_confirm')}
            {' '}{forceDelete === channelId(profile)
              ? localize('com_lsm_channel_delete_force_help')
              : localize('com_lsm_channel_delete_help')}
          </p>}
        </li>)}
      </ul> : <p className="rounded-lg border border-dashed border-border-medium p-5 text-sm text-text-secondary">{localize('com_lsm_channel_empty')}</p>
    )}
    {editor && <form aria-label={localize('com_lsm_channel_configuration')} className="space-y-4 rounded-lg border border-border-medium bg-surface-secondary p-4" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <h3 className="font-semibold text-text-primary">{editor.original ? localize('com_lsm_channel_edit_name', { name: channelLabel(editor.original) }) : localize('com_lsm_channel_add')}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        {(!editor.original || editor.original.name) && <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_name')}</span>
          <input aria-label={localize('com_lsm_channel_name')} className={input} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder={localize('com_lsm_channel_name_example')} maxLength={64} required />
        </label>}
        <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_protocol')}</span>
          <select aria-label={localize('com_lsm_channel_provider')} className={input} value={draft.provider} disabled={Boolean(editor.original)} onChange={(event) => {
            const provider = event.target.value as Kind;
            setDraft({ ...draft, provider, base: kinds.find((kind) => kind.value === provider)?.defaultUrl ?? '' });
          }}>
            {kinds.map((kind) => <option key={kind.value} value={kind.value}>{localize(kind.label)}</option>)}
          </select>
        </label>
        <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_base_url')}</span>
          <input aria-label={localize('com_lsm_channel_model_base_url')} className={input} value={draft.base} onChange={(event) => setDraft({ ...draft, base: event.target.value })} required />
        </label>
        <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_key')}</span>
          <input type="password" autoComplete="new-password" aria-label={localize('com_lsm_channel_model_key')} className={input} value={draft.apiKey} onChange={(event) => setDraft({ ...draft, apiKey: event.target.value })} placeholder={editor.original?.configured ? localize('com_lsm_channel_keep_key') : localize('com_lsm_channel_optional_key')} />
        </label>
        <label className="space-y-1 text-sm text-text-primary sm:col-span-2"><span>{localize('com_lsm_channel_models')}</span>
          <textarea aria-label={localize('com_lsm_channel_identifiers')} className={input} value={draft.models} onChange={(event) => setDraft({ ...draft, models: event.target.value })} rows={3} required />
        </label>
        {draftModels.length > 0 && <div className="space-y-2 sm:col-span-2">
          <p className="text-sm text-text-primary">{localize('com_lsm_channel_context_window')}</p>
          {draftModels.map((model) => <label key={model} className="flex items-center gap-3 text-xs text-text-secondary">
            <span className="min-w-0 flex-1 break-all">{model}</span>
            <input className={input + ' max-w-40'} type="number" min={1} max={2000000}
              placeholder={localize('com_ui_unknown')} aria-label={localize('com_lsm_channel_context_model', { model })}
              value={draft.contexts[model] ?? ''} onChange={(event) => setDraft({ ...draft,
                contexts: { ...draft.contexts, [model]: event.target.value } })} />
          </label>)}
          <p className="text-xs text-text-tertiary">{localize('com_lsm_channel_context_help')}</p>
        </div>}
        {draftModels.length > 0 && <details className="space-y-3 rounded-lg border border-border-light p-3 sm:col-span-2">
          <summary className="cursor-pointer text-sm font-medium text-text-primary">{localize('com_lsm_channel_defaults')}</summary>
          {draftModels.map((model) => <div key={model} className="space-y-2">
            <p className="break-all text-sm text-text-secondary">{model}</p>
            <SamplingFields provider={draft.provider} prefix={model} value={draft.sampling[model] ?? samplingDraft()}
              onChange={(value) => setDraft((previous) => ({ ...previous,
                sampling: { ...previous.sampling, [model]: value } }))} />
          </div>)}
        </details>}
        {draft.provider === 'openai' && <label className="flex items-center gap-2 text-sm text-text-primary sm:col-span-2">
          <input type="checkbox" checked={draft.includeUsage} onChange={(event) => setDraft({ ...draft, includeUsage: event.target.checked })} />
          {localize('com_lsm_channel_usage')}
        </label>}
      </div>
      <p className="text-xs text-text-secondary">{editor.original?.name ? localize('com_lsm_channel_rename_help') : ''}{' '}{localize('com_lsm_channel_key_help')}</p>
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy || !draft.models.trim()} className={button}>{busy ? localize('com_lsm_channel_saving') : localize('com_lsm_channel_save')}</button>
        <button type="button" disabled={busy} className={button} onClick={() => { setEditor(null); setError(''); }}>{localize('com_ui_cancel')}</button>
      </div>
    </form>}
  </div>;
}
