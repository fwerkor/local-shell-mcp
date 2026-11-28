import { useEffect, useRef, useState } from 'react';
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import { X } from 'lucide-react';
import useLocalize from '~/hooks/useLocalize';
import type { TranslationKeys } from '~/hooks/useLocalize';
import { useQueryClient } from '@tanstack/react-query';
import { apiBaseUrl, request, QueryKeys } from 'librechat-data-provider';
import SamplingFields, { samplingDraft, parseSampling } from '~/components/Endpoints/SamplingFields';
import type { Sampling, SamplingDraft } from '~/components/Endpoints/SamplingFields';

type Kind = 'openai' | 'openai-responses' | 'anthropic' | 'google' | 'virtual';
type Member = { channel: string; model: string; weight: number };
type VirtualModel = { id: number; model: string; members: Member[] };
const strategies = [
  ['priority', 'com_lsm_channel_priority'], ['round_robin', 'com_lsm_channel_round_robin'],
  ['weighted_round_robin', 'com_lsm_channel_weighted_round_robin'],
  ['least_connections', 'com_lsm_channel_least_connections'], ['least_latency', 'com_lsm_channel_least_latency'],
] as const;
type Source = 'default' | 'environment' | 'saved' | 'named';
type Profile = {
  name?: string;
  provider: Kind;
  base_url: string;
  models: string[];
  model_contexts?: Record<string, number>;
  model_sampling?: Record<string, Sampling>;
  auto_discover?: boolean;
  discovered_model_contexts?: Record<string, number>;
  model_context_overrides?: Record<string, number>;
  model_sync_at?: number | null;
  model_sync_error?: string | null;
  configured: boolean;
  auth_method?: string;
  oauth_error?: string | null;
  source: Source;
  routes?: Record<string, Member[]>;
  strategy?: string;
  session_affinity?: boolean;
};
type Profiles = { providers: Profile[] };
type DiscoveredModels = { models: string[]; model_contexts: Record<string, number> };
type Draft = { name: string; provider: Kind; base: string; models: string;
  autoDiscover: boolean; reportedContexts: Record<string, number>;
  contexts: Record<string, string>; sampling: Record<string, SamplingDraft>; apiKey: string;
  strategy: string; affinity: boolean; virtualModels: VirtualModel[] };
type Editor = { original: Profile | null };
type AccountMethod = { id: string; label: TranslationKeys; defaultName: string };
const accountMethods: AccountMethod[] = [
  { id: 'chatgpt', label: 'com_lsm_channel_oauth_chatgpt', defaultName: 'Codex' },
];
type Authorization = { method: AccountMethod; name: string; reauthorize: boolean; manual: boolean;
  flow?: string; authorizationUrl?: string };
export const isLoopback = (hostname = window.location.hostname) => /^(?:localhost|127(?:\.\d{1,3}){3}|\[::1\]|::1)$/i.test(hostname);
const statusPath = (url: string, flow: string) => url + '/oauth/status?flow=' + encodeURIComponent(flow);

const input = 'w-full rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary';
const button = 'rounded-lg border border-border-medium px-3 py-2 text-sm text-text-primary hover:bg-surface-secondary disabled:opacity-40';
const kinds: { value: Kind; label: TranslationKeys; defaultUrl: string }[] = [
  { value: 'openai', label: 'com_lsm_channel_protocol_openai', defaultUrl: 'https://api.openai.com/v1' },
  { value: 'openai-responses', label: 'com_lsm_channel_protocol_responses', defaultUrl: 'https://api.openai.com/v1' },
  { value: 'anthropic', label: 'com_lsm_channel_protocol_anthropic', defaultUrl: 'https://api.anthropic.com/v1' },
  { value: 'google', label: 'com_lsm_channel_protocol_google', defaultUrl: 'https://generativelanguage.googleapis.com/v1beta' },
];
const channelId = (profile: Profile) => profile.name ?? 'legacy:' + profile.provider;
const newDraft = (): Draft => ({ name: '', provider: 'openai', base: kinds[0].defaultUrl,
  autoDiscover: true, reportedContexts: {},
  models: '', contexts: {}, sampling: {}, apiKey: '', strategy: 'priority', affinity: true, virtualModels: [] });
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
    if (provider === 'virtual') return localize('com_lsm_channel_virtual');
    const key = kinds.find((kind) => kind.value === provider)?.label;
    return key ? localize(key) : provider;
  };
  const channelLabel = (profile: Profile) => profile.name ?? localize('com_lsm_channel_legacy_name', { protocol: protocolLabel(profile.provider) });
  const client = useQueryClient();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [addMenu, setAddMenu] = useState(false);
  const addMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (addMenu) {
      addMenuRef.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    }
  }, [addMenu]);
  const [authorization, setAuthorization] = useState<Authorization | null>(null);
  const [callback, setCallback] = useState('');
  const [oauthBusy, setOauthBusy] = useState(false);
  const [oauthError, setOauthError] = useState('');
  const [callbackSent, setCallbackSent] = useState(false);
  const [draft, setDraft] = useState<Draft>(newDraft);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [forceDelete, setForceDelete] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [preview, setPreview] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [previewError, setPreviewError] = useState('');
  const [previewRevision, setPreviewRevision] = useState(0);
  const url = apiBaseUrl() + '/api/lsm/providers';
  const channels = profiles.filter((profile) => profile.source !== 'default');
  const isVirtual = draft.provider === 'virtual';
  const draftModels = isVirtual ? draft.virtualModels.map((model) => model.model.trim()).filter(Boolean) : [...new Set(draft.models.split(/[\n,]/).map((model) => model.trim()).filter(Boolean))];

  useEffect(() => {
    let live = true;
    const load = () => request.get<Profiles>(url).then((data) => {
      if (live) setProfiles(data.providers);
    }).catch((reason) => {
      if (live) setError(errorMessage(reason));
    }).finally(() => { if (live) setLoading(false); });
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    return () => { live = false; window.clearInterval(timer); };
  }, [url]);

  const refresh = async () => {
    const data = await request.get<Profiles>(url);
    setProfiles(data.providers);
    await Promise.all([QueryKeys.models, QueryKeys.endpoints, QueryKeys.tokenConfig].map((name) =>
      client.invalidateQueries({ queryKey: [name], refetchType: 'all' })));
  };
  const beginAdd = (virtual = false) => {
    setAddMenu(false);
    setEditor({ original: null });
    setDraft(virtual ? { ...newDraft(), provider: 'virtual', base: '', autoDiscover: false } : newDraft());
    setPreview('idle');
    setPreviewError('');
    setConfirmDelete(null);
    setForceDelete(null);
    setError('');
    setSuccess('');
  };
  const closeEditor = () => {
    if (busy) return;
    setEditor(null);
    setDraft(newDraft());
    setError('');
  };
  const beginEdit = (profile: Profile) => {
    setEditor({ original: profile });
    setPreview('idle');
    setPreviewError('');
    setDraft({
      name: profile.name ?? '',
      provider: profile.provider,
      base: profile.base_url,
      models: profile.models.join('\n'),
      autoDiscover: profile.auto_discover === true,
      reportedContexts: profile.discovered_model_contexts ?? {},
      contexts: Object.fromEntries(Object.entries(
        profile.auto_discover ? (profile.model_context_overrides ?? {}) : (profile.model_contexts ?? {}),
      ).map(([key, value]) => [key, String(value)])),
      sampling: Object.fromEntries(Object.entries(profile.model_sampling ?? {}).map(([model, value]) => [model, samplingDraft(value)])),
      apiKey: '',
      strategy: profile.strategy ?? 'priority', affinity: profile.session_affinity ?? true,
      virtualModels: Object.entries(profile.routes ?? {}).map(([model, members], id) => ({ id, model, members })),
    });
    setConfirmDelete(null);
    setForceDelete(null);
    setError('');
    setSuccess('');
  };
  const beginOAuth = async (pending: Authorization) => {
    setOauthBusy(true);
    setOauthError('');
    setCallbackSent(false);
    // Open synchronously with the initiating click to avoid popup blockers.
    const popup = window.open('', '_blank');
    if (popup) popup.opener = null;
    try {
      const result = await request.post(url + '/oauth/start', {
        method: pending.method.id, name: pending.name, reauthorize: pending.reauthorize,
        manual: pending.manual,
      }) as { flow: string; authorization_url: string; manual: boolean };
      setAuthorization({ ...pending, flow: result.flow, authorizationUrl: result.authorization_url, manual: result.manual });
      if (popup) popup.location.href = result.authorization_url;
    } catch (reason) {
      popup?.close();
      setOauthError(errorMessage(reason));
    } finally {
      setOauthBusy(false);
    }
  };
  const selectAccount = (method: AccountMethod, profile?: Profile) => {
    setAddMenu(false);
    setEditor(null);
    setError('');
    setSuccess('');
    setCallback('');
    setOauthError('');
    setCallbackSent(false);
    let name = profile?.name ?? method.defaultName;
    for (let suffix = 2; !profile && channels.some((item) => item.name?.toLowerCase() === name.toLowerCase()); suffix++) {
      name = method.defaultName + ' ' + suffix;
    }
    const pending = { method, name, reauthorize: Boolean(profile), manual: !isLoopback() };
    setAuthorization(pending);
    if (!pending.manual) void beginOAuth(pending);
  };
  const cancelOAuth = async () => {
    const flow = authorization?.flow;
    setAuthorization(null);
    setCallback('');
    setCallbackSent(false);
    setOauthError('');
    if (flow) {
      try { await request.delete(statusPath(url, flow)); } catch { /* expired or already completed */ }
    }
  };
  const submitCallback = async () => {
    if (!authorization?.flow || !callback.trim()) return;
    setOauthBusy(true);
    setOauthError('');
    try {
      await request.post(statusPath(url, authorization.flow), { callback_url: callback.trim() });
      setCallback('');
      setCallbackSent(true);
    } catch (reason) {
      setOauthError(errorMessage(reason));
    } finally {
      setOauthBusy(false);
    }
  };
  useEffect(() => {
    if (!authorization?.flow) return;
    let live = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const result = await request.get(statusPath(url, authorization.flow!)) as
          { status: string; name?: string; error?: string };
        if (!live) return;
        if (result.status === 'complete') {
          const data = await request.get<Profiles>(url);
          if (!live) return;
          setProfiles(data.providers);
          const connected = data.providers.find((item) => item.name === result.name);
          if (connected) beginEdit(connected);
          setAuthorization(null);
          setCallback('');
          setSuccess(localize('com_lsm_channel_oauth_connected'));
          await Promise.all([QueryKeys.models, QueryKeys.endpoints, QueryKeys.tokenConfig].map((name) =>
            client.invalidateQueries({ queryKey: [name], refetchType: 'all' })));
          return;
        }
        if (result.status !== 'pending') {
          setOauthError(result.error ?? localize('com_lsm_channel_oauth_ended'));
          setAuthorization((current) => current ? { ...current, flow: undefined, authorizationUrl: undefined } : null);
          setCallbackSent(false);
          return;
        }
        if (live) timer = window.setTimeout(() => void poll(), 1000);
      } catch (reason) {
        if (live) {
          setOauthError(errorMessage(reason));
          setAuthorization((current) => current ? { ...current, flow: undefined, authorizationUrl: undefined } : null);
          setCallbackSent(false);
        }
      }
    };
    void poll();
    return () => { live = false; if (timer != null) window.clearTimeout(timer); };
  }, [authorization?.flow, url]);
  const original = editor?.original;
  const base = draft.base.trim().replace(/\/+$/, '');
  const apiKey = draft.apiKey.trim();
  // Preview only; the server independently refreshes and validates on Save.
  // A superseded connection or a disabled toggle must never accept a late reply.
  useEffect(() => {
    setPreviewError('');
    if (!editor || !draft.autoDiscover || !base) {
      setPreview('idle');
      return;
    }
    let local = false;
    try {
      const parsed = new URL(base);
      local = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname);
      if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && local)) {
        setPreview('idle');
        return;
      }
    } catch {
      setPreview('idle');
      return;
    }
    const savedConnection = original && original.base_url.replace(/\/+$/, '') === base
      && original.provider === draft.provider;
    if (!apiKey && !savedConnection && !local && base === kinds.find((kind) => kind.value === draft.provider)?.defaultUrl) {
      setPreview('idle');
      return;
    }
    let live = true;
    setPreview('loading');
    const timer = window.setTimeout(() => {
      request.post(url + '/discover', {
        provider: draft.provider,
        base_url: base,
        ...(apiKey ? { api_key: apiKey } : {}),
        ...(savedConnection && original ? { existing_channel: original.name ?? original.provider } : {}),
      }).then((found: DiscoveredModels) => {
        if (!live) return;
        setDraft((previous) => ({
          ...previous,
          models: found.models.join('\n'),
          reportedContexts: found.model_contexts,
        }));
        setPreview('ready');
      }).catch((reason: unknown) => {
        if (!live) return;
        setPreviewError(errorMessage(reason));
        setPreview('error');
      });
    }, 450);
    return () => { live = false; window.clearTimeout(timer); };
  }, [editor, original, draft.autoDiscover, draft.provider, base, apiKey, url, previewRevision]);

  const toggleDiscovery = (enabled: boolean) => {
    setDraft((previous) => ({
      ...previous,
      autoDiscover: enabled,
      // Disabling freezes the effective values in the editable manual catalog.
      contexts: enabled ? previous.contexts : {
        ...Object.fromEntries(Object.entries(previous.reportedContexts).map(([key, value]) => [key, String(value)])),
        ...Object.fromEntries(Object.entries(previous.contexts).filter(([, value]) => value.trim())),
      },
      reportedContexts: enabled ? previous.reportedContexts : {},
    }));
  };
  const refreshSaved = async (profile: Profile) => {
    setBusy(true);
    setError('');
    setSuccess('');
    try {
      const updated: Profiles = await request.post(url + '/refresh', {
        channel: profile.name ?? profile.provider,
      });
      await refresh();
      const current = updated.providers.find((item) => channelId(item) === channelId(profile));
      if (current?.model_sync_error) setError(current.model_sync_error);
      else setSuccess(localize('com_lsm_channel_refreshed'));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
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
      if (isVirtual) {
        if (draft.virtualModels.length !== models.length || new Set(models).size !== models.length ||
            !models.length || draft.virtualModels.some((model) => !model.members.length)) {
          throw new Error(localize('com_lsm_channel_virtual_invalid'));
        }
        const modelSampling = Object.fromEntries(models
          .map((model) => [model, parseSampling(draft.sampling[model] ?? samplingDraft())] as const)
          .filter(([, value]) => Object.keys(value).length > 0));
        await request.put(url, {
          name, provider: 'virtual', strategy: draft.strategy, session_affinity: draft.affinity,
          routes: Object.fromEntries(draft.virtualModels.map((model) => [model.model.trim(), model.members])),
          model_sampling: modelSampling,
          ...(original?.name && name !== original.name ? { previous_name: original.name } : {}),
        });
        await refresh();
        setEditor(null);
        setSuccess(localize('com_lsm_channel_saved'));
        return;
      }
      const contexts = draft.contexts;
      const modelContexts: Record<string, number> = {};
      for (const model of models) {
        const raw = contexts[model]?.trim();
        if (!raw) continue;
        const tokens = Number(raw);
        if (!Number.isInteger(tokens) || tokens < 1 || tokens > 2_000_000) {
          throw new Error(localize('com_lsm_channel_context_invalid'));
        }
        modelContexts[model] = tokens;
      }
      if (!draft.autoDiscover && !models.length) throw new Error(localize('com_lsm_channel_models_required'));
      const modelSampling = Object.fromEntries(models
        .map((model) => [model, parseSampling(draft.sampling[model] ?? samplingDraft(), draft.provider)] as const)
        .filter(([, value]) => Object.keys(value).length > 0));
      await request.put(url, {
        provider: draft.provider,
        base_url: draft.base.trim(),
        models,
        auto_discover: draft.autoDiscover,
        model_contexts: modelContexts,
        model_sampling: modelSampling,
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
  const callbackFields = <>
    <label className="block space-y-1"><span>{localize('com_lsm_channel_oauth_callback_url')}</span>
      <textarea className={input} autoComplete="off" spellCheck={false} rows={3}
        value={callback} onChange={(event) => setCallback(event.target.value)}
        disabled={callbackSent} placeholder="http://127.0.0.1:…/auth/callback?…" />
    </label>
    <button type="button" className={button} disabled={oauthBusy || callbackSent || !callback.trim()}
      onClick={() => void submitCallback()}>{callbackSent ? localize('com_lsm_channel_oauth_completing') : localize('com_lsm_channel_oauth_complete')}</button>
  </>;
  return <div className="space-y-4">
    <div className="space-y-3">
      <p className="text-sm text-text-secondary">{localize('com_lsm_channel_description')}</p>
      <div>
        <button type="button" disabled={busy || authorization != null} onClick={() => setAddMenu((value) => !value)}
          aria-label={localize('com_lsm_channel_add')} aria-expanded={addMenu} aria-haspopup="menu" className={button}>{localize('com_lsm_channel_add')} ▾</button>
        {addMenu && <div ref={addMenuRef} role="menu" aria-label={localize('com_lsm_channel_add')} className="mt-1 w-max min-w-0 max-w-full rounded-lg border border-border-medium bg-surface-primary p-1 shadow-lg">
          <button role="menuitem" type="button" onClick={() => beginAdd()} className="block w-full break-words rounded px-3 py-2 text-left text-sm hover:bg-surface-secondary">{localize('com_lsm_channel_manual_config')}</button>
          {accountMethods.map((method) => <button role="menuitem" type="button" key={method.id}
            onClick={() => selectAccount(method)} className="block w-full break-words rounded px-3 py-2 text-left text-sm hover:bg-surface-secondary">{localize(method.label)}</button>)}
          <button role="menuitem" type="button" onClick={() => beginAdd(true)}
            className="block w-full break-words rounded px-3 py-2 text-left text-sm hover:bg-surface-secondary">{localize('com_lsm_channel_virtual')}</button>
        </div>}
      </div>
    </div>
    {!editor && error && <p role="alert" className="text-sm text-status-error">{error}</p>}
    {!editor && success && <p role="status" className="text-sm text-text-primary">{success}</p>}
    {loading ? <p className="text-sm text-text-secondary">{localize('com_lsm_channel_loading')}</p> : (
      channels.length ? <ul aria-label={localize('com_lsm_channel_configured')} className="divide-y divide-border-light rounded-lg border border-border-light">
        {channels.map((profile) => <li key={channelId(profile)} className="flex flex-wrap items-center justify-between gap-3 p-3">
          <div className="min-w-0 flex-1">
            <p className="break-words font-medium text-text-primary">{channelLabel(profile)}</p>
            <p className="text-xs text-text-secondary">{protocolLabel(profile.provider)} · {localize('com_lsm_channel_model_count', { count: profile.models.length })}
              {profile.auth_method && ' · ' + localize('com_lsm_channel_oauth_account', { name: accountMethods.find((method) => method.id === profile.auth_method)?.defaultName ?? profile.auth_method })}
              {profile.source === 'environment'  ? localize('com_lsm_channel_environment') : ''}
              {profile.source === 'saved' ? localize('com_lsm_channel_legacy') : ''}
            </p>
            {profile.oauth_error && <p className="text-xs text-status-error">{localize('com_lsm_channel_oauth_expired')}</p>}
            {profile.auto_discover && <p className="text-xs text-text-secondary">
              {profile.model_sync_error ? localize('com_lsm_channel_sync_failed') :
                profile.model_sync_at ? localize('com_lsm_channel_synced', { date: new Date(profile.model_sync_at * 1000).toLocaleString() }) : localize('com_lsm_channel_auto_discovery')}
            </p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {profile.auto_discover && <button type="button" className={button} disabled={busy || editor != null}
              onClick={() => void refreshSaved(profile)} aria-label={localize('com_lsm_channel_refresh_name', { name: channelLabel(profile) })}>{localize('com_ui_refresh')}</button>}
            {accountMethods.filter((method) => method.id === profile.auth_method).map((method) =>
              <button type="button" key={method.id} className={button} disabled={busy || authorization != null}
                onClick={() => selectAccount(method, profile)}>{localize('com_lsm_channel_oauth_reauthorize')}</button>)}
            <button type="button" className={button} disabled={busy || authorization != null} onClick={() => beginEdit(profile)} aria-label={localize('com_lsm_channel_edit_name', { name: channelLabel(profile) })}>{localize('com_ui_edit')}</button>
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
    {authorization && (authorization.manual ?
      <div role="dialog" aria-modal="true" aria-label={localize('com_lsm_channel_oauth_connect')} className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
        <section className="max-h-full w-full max-w-md space-y-4 overflow-y-auto rounded-xl border border-border-medium bg-surface-primary p-5 text-sm text-text-primary shadow-lg">
          <h3 className="text-lg font-semibold">{localize(authorization.method.label)}</h3>
          <p>{localize('com_lsm_channel_oauth_manual_intro')}</p>
          <ol className="list-decimal space-y-2 pl-5">
            <li>{localize('com_lsm_channel_oauth_manual_step1')}</li>
            <li>{localize('com_lsm_channel_oauth_manual_step2')}</li>
            <li>{localize('com_lsm_channel_oauth_manual_step3')}</li>
          </ol>
          {!authorization.flow ? <button type="button" className={button} disabled={oauthBusy} onClick={() => void beginOAuth(authorization)}>{localize('com_lsm_channel_oauth_start')}</button> :
            <>
              {callbackFields}
              {authorization.authorizationUrl && <a className="block underline" href={authorization.authorizationUrl} target="_blank" rel="noreferrer">{localize('com_lsm_channel_oauth_reopen')}</a>}
            </>}
          {oauthError && <p role="alert" className="text-status-error">{oauthError}</p>}
          <button type="button" className={button} disabled={oauthBusy} onClick={() => void cancelOAuth()}>{localize('com_ui_cancel')}</button>
        </section>
      </div> :
      <div className="space-y-2 rounded-lg border border-border-medium p-3 text-sm text-text-primary">
        <p role="status">{authorization.flow ? localize('com_lsm_channel_oauth_waiting') : oauthBusy ? localize('com_lsm_channel_oauth_opening') : localize('com_lsm_channel_oauth_authorization')}</p>
        {authorization.authorizationUrl && <a className="underline" href={authorization.authorizationUrl} target="_blank" rel="noreferrer">{localize('com_lsm_channel_oauth_reopen')}</a>}
        {oauthError && <p role="alert" className="text-status-error">{oauthError}</p>}
        {!authorization.flow && !oauthBusy && <button type="button" className={button} onClick={() => void beginOAuth(authorization)}>{localize('com_lsm_channel_oauth_start')}</button>}
        {authorization.flow && <details className="space-y-2">
          <summary className="cursor-pointer">{localize('com_lsm_channel_oauth_missing_callback')}</summary>
          <p>{localize('com_lsm_channel_oauth_local_help')}</p>
          {callbackFields}
        </details>}
        <button type="button" className={button} disabled={oauthBusy} onClick={() => void cancelOAuth()}>{localize('com_ui_cancel')}</button>
      </div>)}
    {editor && <Dialog open onClose={closeEditor} className="relative z-[60]">
      <div className="fixed inset-0 bg-black/50" aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center p-2 sm:p-4">
        <DialogPanel className="flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-border-medium bg-surface-dialog shadow-2xl">
          <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border-light px-4 py-3">
            <DialogTitle className="min-w-0 break-words font-semibold text-text-primary">{editor.original ? localize('com_lsm_channel_edit_name', { name: channelLabel(editor.original) }) : localize('com_lsm_channel_add')}</DialogTitle>
            <button type="button" disabled={busy} onClick={closeEditor} aria-label={localize('com_ui_close')} className="shrink-0 rounded-lg p-1 text-text-secondary hover:bg-surface-hover disabled:opacity-40">
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </header>
          <form aria-label={localize('com_lsm_channel_configuration')} className="flex min-h-0 flex-col" onSubmit={(event) => { event.preventDefault(); void save(); }}>
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain p-4">
              {success && <p role="status" className="text-sm text-text-primary">{success}</p>}
              <div inert={busy ? '' : undefined} className="grid min-w-0 gap-4 sm:grid-cols-2">
                {(!editor.original || editor.original.name) && <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_name')}</span>
                  <input aria-label={localize('com_lsm_channel_name')} className={input} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder={localize('com_lsm_channel_name_example')} maxLength={64} required />
                </label>}
                {isVirtual ? <>
                  <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_strategy')}</span>
                    <select className={input} value={draft.strategy} onChange={(event) => setDraft({ ...draft, strategy: event.target.value })}>
                      {strategies.map(([value, label]) => <option key={value} value={value}>{localize(label)}</option>)}
                    </select>
                  </label>
                  <label className="flex items-center justify-between gap-3 text-sm font-medium text-text-primary sm:col-span-2">
                    {localize('com_lsm_channel_affinity')}
                    <input type="checkbox" role="switch" checked={draft.affinity} onChange={(event) => setDraft({ ...draft, affinity: event.target.checked })} />
                  </label>
                  <div className="space-y-3 sm:col-span-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-text-primary">{localize('com_ui_model')}</span>
                      <button type="button" className={button} onClick={() => setDraft((old) => ({
                        ...old, virtualModels: [...old.virtualModels, { id: Math.max(-1, ...old.virtualModels.map((m) => m.id)) + 1, model: '', members: [] }],
                      }))}>{localize('com_lsm_channel_add_model')}</button>
                    </div>
                    {draft.virtualModels.map((model) => {
                      const update = (next: Partial<VirtualModel>) => setDraft((old) => ({
                        ...old, virtualModels: old.virtualModels.map((m) => m.id === model.id ? { ...m, ...next } : m),
                      }));
                      const candidates = channels.filter((p) => p.provider !== 'virtual').flatMap((p) =>
                        p.models.map((m) => ({ channel: p.name ?? p.provider, model: m, weight: 1 })));
                      const available = candidates.filter((c) => !model.members.some((m) => m.channel === c.channel && m.model === c.model));
                      const limits = model.members.map((m) => channels.find((p) => (p.name ?? p.provider) === m.channel)?.model_contexts?.[m.model]);
                      const limit = limits.length && limits.every((n) => typeof n === 'number') ? Math.min(...limits as number[]) : null;
                      return <div key={model.id} className="space-y-2 rounded-lg border border-border-medium p-3">
                        <div className="flex items-center gap-2">
                          <input className={input} value={model.model} aria-label={localize('com_lsm_channel_identifiers')} placeholder={localize('com_lsm_channel_identifiers')} required
                            onChange={(event) => update({ model: event.target.value })} />
                          <button type="button" className={button} onClick={() => setDraft((old) => ({ ...old, virtualModels: old.virtualModels.filter((m) => m.id !== model.id) }))}>{localize('com_ui_delete')}</button>
                        </div>
                        <p className="text-xs text-text-secondary">{localize('com_ui_context_window')}: {limit ? limit.toLocaleString() : localize('com_ui_unknown')}</p>
                        <p className="text-sm text-text-secondary">{localize('com_lsm_channel_members')}</p>
                        {model.members.map((m, index) => <div key={JSON.stringify([m.channel, m.model])} className="flex flex-wrap items-center gap-2 rounded border border-border-light p-2">
                          {draft.strategy === 'priority' && <button type="button" className={button} disabled={!index}
                            aria-label={localize('com_lsm_channel_move_up')} onClick={() => {
                              const members = [...model.members]; [members[index - 1], members[index]] = [members[index], members[index - 1]];
                              update({ members });
                            }}>↑</button>}
                          <div className="min-w-0 flex-1 break-all text-sm">{m.channel}<div className="text-xs text-text-secondary">{m.model}</div></div>
                          {draft.strategy === 'weighted_round_robin' && <input className={input + ' max-w-24'} type="number" min={1} max={10000} required
                            aria-label={localize('com_lsm_channel_weight')} value={m.weight} onChange={(event) => update({
                              members: model.members.map((item, i) => i === index ? { ...item, weight: Number(event.target.value) } : item),
                            })} />}
                          <button type="button" className={button} onClick={() => update({ members: model.members.filter((_, i) => i !== index) })}>{localize('com_ui_delete')}</button>
                        </div>)}
                        <select className={input} aria-label={localize('com_lsm_channel_add_member')} value="" disabled={!available.length} onChange={(event) => {
                          const selected = available[Number(event.target.value)];
                          if (event.target.value !== '' && selected) update({ members: [...model.members, selected] });
                        }}>
                          <option value="" disabled>{localize('com_lsm_channel_add_member')}</option>
                          {available.map((m, i) => <option key={JSON.stringify([m.channel, m.model])} value={i}>{m.channel} / {m.model}</option>)}
                        </select>
                      </div>;
                    })}
                  </div>
                </> : <>
                <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_protocol')}</span>
                  <select aria-label={localize('com_lsm_channel_provider')} className={input} value={draft.provider} disabled={Boolean(editor.original)} onChange={(event) => {
                    const provider = event.target.value as Kind;
                    setDraft({ ...draft, provider, base: kinds.find((kind) => kind.value === provider)?.defaultUrl ?? '' });
                  }}>
                    {kinds.map((kind) => <option key={kind.value} value={kind.value}>{localize(kind.label)}</option>)}
                  </select>
                </label>
                <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_base_url')}</span>
                  <input aria-label={localize('com_lsm_channel_model_base_url')} className={input} value={draft.base} disabled={Boolean(original?.auth_method)} onChange={(event) => setDraft({ ...draft, base: event.target.value })} required />
                </label>
                {original?.auth_method ? <div className="space-y-1 text-sm text-text-primary">
                  <span>{localize('com_lsm_channel_oauth_authorization')}</span>
                  <p className="text-text-secondary">{original.oauth_error ? localize('com_lsm_channel_oauth_required') : localize('com_lsm_channel_oauth_auto_refresh')}</p>
                </div> : <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_key')}</span>
                  <input type="password" autoComplete="new-password" aria-label={localize('com_lsm_channel_model_key')} className={input} value={draft.apiKey} onChange={(event) => setDraft({ ...draft, apiKey: event.target.value })} placeholder={editor.original?.configured ? localize('com_lsm_channel_keep_key') : localize('com_lsm_channel_optional_key')} />
                </label>}
                <div className="space-y-3 sm:col-span-2">
                  <label className="flex items-center justify-between gap-3 text-sm font-medium text-text-primary">
                    <span>{localize('com_lsm_channel_discover_toggle')}</span>
                    <input type="checkbox" role="switch" aria-label={localize('com_lsm_channel_discover_toggle')}
                      checked={draft.autoDiscover} onChange={(event) => toggleDiscovery(event.target.checked)} />
                  </label>
                  {draft.autoDiscover ? <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs text-text-secondary" role="status">
                        {preview === 'loading' ? localize('com_lsm_channel_discover_loading') : preview === 'ready' ?
                          localize('com_lsm_channel_discover_ready', { count: draftModels.length }) : preview === 'error' ?
                          localize('com_lsm_channel_discover_failed') : localize('com_lsm_channel_discover_count', { count: draftModels.length })}
                      </p>
                      <button type="button" disabled={busy || preview === 'loading' || !base}
                        onClick={() => setPreviewRevision((value) => value + 1)} className={button}
                        aria-label={localize('com_lsm_channel_discover_refresh')}>{localize('com_ui_refresh')}</button>
                    </div>
                    {previewError && <p role="alert" className="text-xs text-status-error">{previewError} {localize('com_lsm_channel_discover_manual_help')}</p>}
                    <p className="text-xs text-text-tertiary">{localize('com_lsm_channel_discover_interval')}</p>
                  </> : <label className="space-y-1 text-sm text-text-primary"><span>{localize('com_lsm_channel_models')}</span>
                    <textarea aria-label={localize('com_lsm_channel_identifiers')} className={input} value={draft.models}
                      onChange={(event) => setDraft({ ...draft, models: event.target.value })} rows={3} required />
                  </label>}
                  {draftModels.length > 0 && <div className="max-h-80 space-y-2 overflow-y-auto">
                    <p className="text-sm text-text-primary">{localize('com_lsm_channel_context_window')}</p>
                    {draftModels.map((model) => <label key={model} className="flex items-center gap-3 text-xs text-text-secondary">
                      <span className="min-w-0 flex-1 break-all">{model}
                        {draft.autoDiscover && draft.reportedContexts[model] != null &&
                          <span className="block text-text-tertiary">API: {draft.reportedContexts[model].toLocaleString()}</span>}
                      </span>
                      <input className={input + ' max-w-40'} type="number" min={1} max={2000000}
                        placeholder={draft.autoDiscover && draft.reportedContexts[model] != null ?
                          String(draft.reportedContexts[model]) : localize('com_ui_unknown')}
                        aria-label={localize('com_lsm_channel_context_model', { model })} value={draft.contexts[model] ?? ''}
                        onChange={(event) => setDraft({ ...draft,
                          contexts: { ...draft.contexts, [model]: event.target.value } })} />
                    </label>)}
                    {draft.autoDiscover && <p className="text-xs text-text-tertiary">{localize('com_lsm_channel_discover_context_help')}</p>}
                  </div>}
                </div>
                </>}
                {draftModels.length > 0 && <details className="space-y-3 rounded-lg border border-border-light p-3 sm:col-span-2">
                  <summary className="cursor-pointer text-sm font-medium text-text-primary">{localize('com_lsm_channel_defaults')}</summary>
                  {draftModels.map((model) => <div key={model} className="space-y-2">
                    <p className="break-all text-sm text-text-secondary">{model}</p>
                    <SamplingFields provider={draft.provider} prefix={model} value={draft.sampling[model] ?? samplingDraft()}
                      onChange={(value) => setDraft((previous) => ({ ...previous,
                        sampling: { ...previous.sampling, [model]: value } }))} />
                  </div>)}
                </details>}
              </div>
              <p className="text-xs text-text-secondary">{editor.original?.name ? localize('com_lsm_channel_rename_help') : ''}{' '}{!isVirtual && localize('com_lsm_channel_key_help')}</p>
            </div>
            <footer className="shrink-0 space-y-2 border-t border-border-light p-4">
              {error && <p role="alert" className="break-words text-sm text-status-error">{error}</p>}
              <div className="flex flex-wrap justify-end gap-2">
                <button type="button" disabled={busy} className={button} onClick={closeEditor}>{localize('com_ui_cancel')}</button>
                <button type="submit" disabled={busy || (!isVirtual && !draft.base.trim())} className={button}>{busy ? localize('com_lsm_channel_saving') : localize('com_lsm_channel_save')}</button>
              </div>
            </footer>
          </form>
        </DialogPanel>
      </div>
    </Dialog>}
  </div>;
}
