import useLocalize from '~/hooks/useLocalize';
import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { ChevronDown, CirclePlus, Plug, RefreshCw, Trash2 } from 'lucide-react';
import { useControllerServices } from '~/components/LSM/hooks';

type Server = {
  name: string;
  transport: 'stdio' | 'streamable_http';
  enabled: boolean;
  command?: string | null;
  args?: string[];
  cwd?: string | null;
  url?: string | null;
  env_keys?: string[];
  header_keys?: string[];
  tool_count?: number;
  refreshed_at?: string | null;
};
type Action = 'enable' | 'disable' | 'remove' | 'refresh' | 'env_set' | 'env_unset' | 'header_set' | 'header_unset';
const fieldStyle = 'w-full min-w-0 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary';
const buttonStyle = 'rounded-lg border border-border-medium px-3 py-2 text-xs text-text-primary hover:bg-surface-hover disabled:opacity-40';
const iconStyle = 'rounded-lg p-2 text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:opacity-40';

/** LibreChat's MCP sidebar manages Controller-persisted nested servers, never LibreChat's registry. */
export default function LsmNestedMcpPanel() {
  const localize = useLocalize();
  const { read, write } = useControllerServices();
  const [servers, setServers] = useState<Server[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [adding, setAdding] = useState(false);
  const [expanded, setExpanded] = useState('');
  const [name, setName] = useState('');
  const [transport, setTransport] = useState<'stdio' | 'streamable_http'>('streamable_http');
  const [endpoint, setEndpoint] = useState('');
  const [argumentsText, setArgumentsText] = useState('');
  const [editing, setEditing] = useState('');
  const [editTransport, setEditTransport] = useState<'stdio' | 'streamable_http'>('streamable_http');
  const [editEndpoint, setEditEndpoint] = useState('');
  const [editArgs, setEditArgs] = useState('');
  const [editCwd, setEditCwd] = useState('');
  const [credentialKind, setCredentialKind] = useState<'header' | 'env'>('header');
  const [credentialKey, setCredentialKey] = useState('');
  const [credentialValue, setCredentialValue] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await read<{ servers: Server[] }>('nested-mcp');
      setServers(result.servers ?? []);
      setError('');
    } catch (err) { setError(String(err)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const manage = async (action: Action, server: Server, key?: string, value?: string) => {
    if (pending) return;
    if (action === 'remove' && !window.confirm('Remove nested MCP server ' + server.name + '?')) return;
    setPending(true); setError(''); setNotice('');
    try {
      const result = await write<{ refresh_error?: string }>('nested-mcp', {
        action, name: server.name,
        ...(key ? { key } : {}),
        ...(value !== undefined ? { value } : {}),
      });
      setNotice(result.refresh_error || (server.name + ' · ' + action + ' complete'));
      if (action.endsWith('_set') || action.endsWith('_unset')) {
        setCredentialKey(''); setCredentialValue('');
      }
      await refresh();
    } catch (err) { setError(String(err)); }
    finally { setPending(false); }
  };
  const beginEdit = (server: Server) => {
    if (editing === server.name) { setEditing(''); return; }
    setEditing(server.name);
    setEditTransport(server.transport);
    setEditEndpoint(server.transport === 'stdio' ? server.command || '' : server.url || '');
    setEditArgs((server.args || []).join(' '));
    setEditCwd(server.cwd || '');
  };
  const updateServer = async (event: FormEvent, server: Server) => {
    event.preventDefault();
    if (pending || !editEndpoint) return;
    setPending(true); setError(''); setNotice('');
    try {
      const parameters = editTransport === 'stdio'
        ? { transport: editTransport, command: editEndpoint.trim(),
            args: editArgs.trim() ? editArgs.trim().split(/\s+/) : [], cwd: editCwd.trim() || '.' }
        : { transport: editTransport, url: editEndpoint.trim() };
      await write('nested-mcp', { action: 'update', name: server.name, ...parameters });
      setEditing('');
      setNotice(localize('com_lsm_mcp_connection_updated'));
      await refresh();
    } catch (err) { setError(String(err)); }
    finally { setPending(false); }
  };
  const addServer = async (event: FormEvent) => {
    event.preventDefault();
    if (!name || !endpoint || pending) return;
    setPending(true); setError(''); setNotice('');
    try {
      const params = transport === 'streamable_http'
        ? { transport, url: endpoint.trim() }
        : { transport, command: endpoint.trim(), args: argumentsText.trim() ? argumentsText.trim().split(/\s+/) : [] };
      const result = await write<{ refresh_error?: string }>('nested-mcp', {
        action: 'register', name: name.trim(), ...params, enabled: true, refresh: true,
      });
      setNotice(result.refresh_error || localize('com_lsm_mcp_registered'));
      setName(''); setEndpoint(''); setArgumentsText(''); setAdding(false);
      await refresh();
    } catch (err) { setError(String(err)); }
    finally { setPending(false); }
  };

  return (
    <section role="region" aria-label={localize('com_lsm_mcp_region')} className="flex h-full min-h-0 w-full flex-col text-text-primary">
      <header className="flex shrink-0 items-center gap-2 border-b border-border-light px-4 py-3">
        <Plug size={18} />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">{localize('com_lsm_mcp_servers')}</h2>
          <p className="text-xs text-text-secondary">{localize('com_lsm_mcp_managed_by')}</p>
        </div>
        <button className={iconStyle} title={localize('com_lsm_mcp_refresh_list_title')} aria-label={localize('com_lsm_mcp_refresh_list')} onClick={() => void refresh()} disabled={loading || pending}><RefreshCw size={17} /></button>
        <button className={iconStyle} title={localize('com_lsm_mcp_add_server_title')} aria-label={localize('com_lsm_mcp_add_nested')} onClick={() => setAdding(v => !v)}><CirclePlus size={19} /></button>
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-4">
        {error && <p role="alert" className="rounded-lg border border-status-error-border bg-status-error-subtle p-3 text-xs text-status-error">{error}</p>}
        {notice && <p role="status" className="rounded-lg bg-surface-secondary p-3 text-xs">{notice}</p>}
        {adding && (
          <form onSubmit={event => void addServer(event)} className="space-y-3 rounded-xl border border-border-medium bg-surface-secondary p-3">
            <h3 className="text-sm font-semibold">{localize('com_lsm_mcp_add_server')}</h3>
            <label className="block text-xs">{localize('com_lsm_mcp_name')}
              <input className={fieldStyle + ' mt-1'} required maxLength={64} pattern="[A-Za-z0-9._-]+" value={name} onChange={e => setName(e.target.value)} placeholder="my-server" />
            </label>
            <label className="block text-xs">{localize('com_lsm_mcp_transport')}
              <select className={fieldStyle + ' mt-1'} value={transport} onChange={e => setTransport(e.target.value as typeof transport)}>
                <option value="streamable_http">{localize('com_lsm_mcp_streamable_http')}</option><option value="stdio">{localize('com_lsm_mcp_local_stdio')}</option>
              </select>
            </label>
            <label className="block text-xs">{transport === 'stdio' ? localize('com_lsm_mcp_executable') : localize('com_lsm_mcp_server_url')}
              <input className={fieldStyle + ' mt-1'} required value={endpoint} onChange={e => setEndpoint(e.target.value)}
                placeholder={transport === 'stdio' ? 'npx' : 'https://example.org/mcp'} />
            </label>
            {transport === 'stdio' && <label className="block text-xs">{localize('com_lsm_mcp_arguments_space')}
              <input className={fieldStyle + ' mt-1'} value={argumentsText} onChange={e => setArgumentsText(e.target.value)} placeholder="-y @vendor/server" />
            </label>}
            <p className="text-xs text-text-secondary">{localize('com_lsm_mcp_secrets_after_registration')}</p>
            <div className="flex justify-end gap-2">
              <button type="button" className={buttonStyle} onClick={() => setAdding(false)}>{localize('com_lsm_mcp_cancel')}</button>
              <button type="submit" disabled={pending} className={buttonStyle}>{localize('com_lsm_mcp_register')}</button>
            </div>
          </form>
        )}
        {loading && <p className="p-4 text-center text-xs text-text-secondary">{localize('com_lsm_mcp_loading')}</p>}
        {!loading && servers.length === 0 && <p className="rounded-xl border border-border-light p-5 text-center text-xs text-text-secondary">{localize('com_lsm_mcp_empty')}</p>}
        {servers.map(server => (
          <article key={server.name} className="rounded-xl border border-border-light bg-surface-primary">
            <button type="button" className="flex w-full items-center gap-2 p-3 text-left" onClick={() => setExpanded(v => v === server.name ? '' : server.name)}
              aria-expanded={expanded === server.name}>
              <span className={'size-2 shrink-0 rounded-full ' + (server.enabled ? 'bg-status-success' : 'bg-surface-active')} />
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-sm font-medium">{server.name}</h3>
                <p className="truncate text-xs text-text-secondary">{server.transport === 'stdio' ? (server.command || 'stdio') : server.url} · {server.tool_count ?? 0} {localize('com_lsm_mcp_tools')}</p>
              </div>
              <ChevronDown size={15} className={'shrink-0 transition-transform ' + (expanded === server.name ? 'rotate-180' : '')} />
            </button>
            {expanded === server.name && (
              <div className="space-y-3 border-t border-border-light p-3">
                <div className="flex flex-wrap gap-2">
                  <button className={buttonStyle} disabled={pending} onClick={() => beginEdit(server)}>{localize('com_lsm_mcp_edit')}</button>
                  <button className={buttonStyle} disabled={pending} onClick={() => void manage(server.enabled ? 'disable' : 'enable', server)}>{server.enabled ? localize('com_lsm_mcp_disable') : localize('com_lsm_mcp_enable')}</button>
                  <button className={buttonStyle} disabled={pending} onClick={() => void manage('refresh', server)}>{localize('com_lsm_mcp_refresh_tools')}</button>
                  <button className={buttonStyle + ' inline-flex items-center gap-1 text-status-error'} disabled={pending} onClick={() => void manage('remove', server)}><Trash2 size={13} /> {localize('com_lsm_mcp_remove')}</button>
                </div>
                {editing === server.name && (
                  <form onSubmit={event => void updateServer(event, server)} className="space-y-2 rounded-lg bg-surface-secondary p-3">
                    <label className="block text-xs">{localize('com_lsm_mcp_transport')}
                      <select className={fieldStyle + ' mt-1'} value={editTransport} onChange={event => setEditTransport(event.target.value as typeof editTransport)}>
                        <option value="streamable_http">{localize('com_lsm_mcp_streamable_http')}</option><option value="stdio">{localize('com_lsm_mcp_local_stdio')}</option>
                      </select>
                    </label>
                    <label className="block text-xs">{editTransport === 'stdio' ? localize('com_lsm_mcp_executable') : localize('com_lsm_mcp_server_url')}
                      <input required className={fieldStyle + ' mt-1'} value={editEndpoint} onChange={event => setEditEndpoint(event.target.value)} />
                    </label>
                    {editTransport === 'stdio' && <>
                      <label className="block text-xs">{localize('com_lsm_mcp_arguments')}
                        <input className={fieldStyle + ' mt-1'} value={editArgs} onChange={event => setEditArgs(event.target.value)} />
                      </label>
                      <label className="block text-xs">{localize('com_lsm_mcp_working_directory')}
                        <input className={fieldStyle + ' mt-1'} value={editCwd} onChange={event => setEditCwd(event.target.value)} placeholder="." />
                      </label>
                    </>}
                    <p className="text-xs text-text-secondary">{localize('com_lsm_mcp_credentials_retained')}</p>
                    <button type="submit" className={buttonStyle} disabled={pending}>{localize('com_lsm_mcp_save_connection')}</button>
                  </form>
                )}
                {server.refreshed_at && <p className="text-xs text-text-secondary">{localize('com_lsm_mcp_last_refreshed')} {new Date(server.refreshed_at).toLocaleString()}</p>}
                <div className="space-y-2 border-t border-border-light pt-3">
                  <p className="text-xs font-medium">{localize('com_lsm_mcp_credentials')}</p>
                  {[['com_lsm_mcp_environment', 'env_keys', 'env_unset'], ['com_lsm_mcp_headers', 'header_keys', 'header_unset']].map(([label, property, action]) => (
                    <div key={property} className="space-y-1">
                      <p className="text-xs text-text-secondary">{localize(label as 'com_lsm_mcp_environment' | 'com_lsm_mcp_headers')}</p>
                      {(server[property as 'env_keys' | 'header_keys'] || []).map(key => (
                        <div key={key} className="flex items-center justify-between gap-2 text-xs">
                          <span className="truncate">{key} · ••••••</span>
                          <button className={iconStyle} title={localize('com_lsm_mcp_remove') + ' ' + key} onClick={() => void manage(action as Action, server, key)} disabled={pending}><Trash2 size={14} /></button>
                        </div>
                      ))}
                    </div>
                  ))}
                  <div className="flex gap-1">
                    <select aria-label={localize('com_lsm_mcp_credential_type')} className={fieldStyle} value={credentialKind} onChange={e => setCredentialKind(e.target.value as typeof credentialKind)}>
                      <option value="header">{localize('com_lsm_mcp_header')}</option><option value="env">{localize('com_lsm_mcp_environment')}</option>
                    </select>
                    <input aria-label={localize('com_lsm_mcp_credential_name')} className={fieldStyle} placeholder="Name" value={credentialKey} onChange={e => setCredentialKey(e.target.value)} />
                  </div>
                  <input aria-label={localize('com_lsm_mcp_credential_value')} type="password" autoComplete="off" className={fieldStyle} placeholder="Value" value={credentialValue} onChange={e => setCredentialValue(e.target.value)} />
                  <button className={buttonStyle} disabled={pending || !credentialKey || !credentialValue}
                    onClick={() => void manage(credentialKind === 'header' ? 'header_set' : 'env_set', server, credentialKey, credentialValue)}>
                    {localize('com_lsm_mcp_save_credential')}
                  </button>
                </div>
              </div>
            )}
          </article>
        ))}
        <p className="text-xs text-text-secondary">{localize('com_lsm_mcp_explanation')}</p>
      </div>
    </section>
  );
}
