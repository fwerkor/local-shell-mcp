import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { ChevronDown, CirclePlus, Plug, RefreshCw, Trash2 } from 'lucide-react';
import { read, write } from '~/components/LSM/api';

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
      setNotice(result.refresh_error || 'Nested MCP registered');
      setName(''); setEndpoint(''); setArgumentsText(''); setAdding(false);
      await refresh();
    } catch (err) { setError(String(err)); }
    finally { setPending(false); }
  };

  return (
    <section role="region" aria-label="Nested MCP servers" className="flex h-full min-h-0 w-full flex-col text-text-primary">
      <header className="flex shrink-0 items-center gap-2 border-b border-border-light px-4 py-3">
        <Plug size={18} />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">MCP servers</h2>
          <p className="text-xs text-text-secondary">Managed by LSM Controller</p>
        </div>
        <button className={iconStyle} title="Refresh list" aria-label="Refresh MCP list" onClick={() => void refresh()} disabled={loading || pending}><RefreshCw size={17} /></button>
        <button className={iconStyle} title="Add server" aria-label="Add nested MCP" onClick={() => setAdding(v => !v)}><CirclePlus size={19} /></button>
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-4">
        {error && <p role="alert" className="rounded-lg border border-red-500/40 p-3 text-xs text-red-500">{error}</p>}
        {notice && <p role="status" className="rounded-lg bg-surface-secondary p-3 text-xs">{notice}</p>}
        {adding && (
          <form onSubmit={event => void addServer(event)} className="space-y-3 rounded-xl border border-border-medium bg-surface-secondary p-3">
            <h3 className="text-sm font-semibold">Add nested MCP server</h3>
            <label className="block text-xs">Name
              <input className={fieldStyle + ' mt-1'} required maxLength={64} pattern="[A-Za-z0-9._-]+" value={name} onChange={e => setName(e.target.value)} placeholder="my-server" />
            </label>
            <label className="block text-xs">Transport
              <select className={fieldStyle + ' mt-1'} value={transport} onChange={e => setTransport(e.target.value as typeof transport)}>
                <option value="streamable_http">Streamable HTTP</option><option value="stdio">Local stdio</option>
              </select>
            </label>
            <label className="block text-xs">{transport === 'stdio' ? 'Executable' : 'Server URL'}
              <input className={fieldStyle + ' mt-1'} required value={endpoint} onChange={e => setEndpoint(e.target.value)}
                placeholder={transport === 'stdio' ? 'npx' : 'https://example.org/mcp'} />
            </label>
            {transport === 'stdio' && <label className="block text-xs">Arguments (space-separated)
              <input className={fieldStyle + ' mt-1'} value={argumentsText} onChange={e => setArgumentsText(e.target.value)} placeholder="-y @vendor/server" />
            </label>}
            <p className="text-xs text-text-secondary">Secrets can be added after registration. Commands run on the LSM Controller.</p>
            <div className="flex justify-end gap-2">
              <button type="button" className={buttonStyle} onClick={() => setAdding(false)}>Cancel</button>
              <button type="submit" disabled={pending} className={buttonStyle}>Register</button>
            </div>
          </form>
        )}
        {loading && <p className="p-4 text-center text-xs text-text-secondary">Loading LSM MCP servers…</p>}
        {!loading && servers.length === 0 && <p className="rounded-xl border border-border-light p-5 text-center text-xs text-text-secondary">No nested MCP servers. Add one to use its tools through LSM.</p>}
        {servers.map(server => (
          <article key={server.name} className="rounded-xl border border-border-light bg-surface-primary">
            <button type="button" className="flex w-full items-center gap-2 p-3 text-left" onClick={() => setExpanded(v => v === server.name ? '' : server.name)}
              aria-expanded={expanded === server.name}>
              <span className={'size-2 shrink-0 rounded-full ' + (server.enabled ? 'bg-green-500' : 'bg-gray-400')} />
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-sm font-medium">{server.name}</h3>
                <p className="truncate text-xs text-text-secondary">{server.transport === 'stdio' ? (server.command || 'stdio') : server.url} · {server.tool_count ?? 0} tools</p>
              </div>
              <ChevronDown size={15} className={'shrink-0 transition-transform ' + (expanded === server.name ? 'rotate-180' : '')} />
            </button>
            {expanded === server.name && (
              <div className="space-y-3 border-t border-border-light p-3">
                <div className="flex flex-wrap gap-2">
                  <button className={buttonStyle} disabled={pending} onClick={() => void manage(server.enabled ? 'disable' : 'enable', server)}>{server.enabled ? 'Disable' : 'Enable'}</button>
                  <button className={buttonStyle} disabled={pending} onClick={() => void manage('refresh', server)}>Refresh tools</button>
                  <button className={buttonStyle + ' inline-flex items-center gap-1 text-red-500'} disabled={pending} onClick={() => void manage('remove', server)}><Trash2 size={13} /> Remove</button>
                </div>
                {server.refreshed_at && <p className="text-xs text-text-secondary">Last refreshed: {new Date(server.refreshed_at).toLocaleString()}</p>}
                <div className="space-y-2 border-t border-border-light pt-3">
                  <p className="text-xs font-medium">Credentials</p>
                  {[['Environment', 'env_keys', 'env_unset'], ['Headers', 'header_keys', 'header_unset']].map(([label, property, action]) => (
                    <div key={property} className="space-y-1">
                      <p className="text-xs text-text-secondary">{label}</p>
                      {(server[property as 'env_keys' | 'header_keys'] || []).map(key => (
                        <div key={key} className="flex items-center justify-between gap-2 text-xs">
                          <span className="truncate">{key} · ••••••</span>
                          <button className={iconStyle} title={'Remove ' + key} onClick={() => void manage(action as Action, server, key)} disabled={pending}><Trash2 size={14} /></button>
                        </div>
                      ))}
                    </div>
                  ))}
                  <div className="flex gap-1">
                    <select aria-label="Credential type" className={fieldStyle} value={credentialKind} onChange={e => setCredentialKind(e.target.value as typeof credentialKind)}>
                      <option value="header">Header</option><option value="env">Environment</option>
                    </select>
                    <input aria-label="Credential name" className={fieldStyle} placeholder="Name" value={credentialKey} onChange={e => setCredentialKey(e.target.value)} />
                  </div>
                  <input aria-label="Credential value" type="password" autoComplete="off" className={fieldStyle} placeholder="Value" value={credentialValue} onChange={e => setCredentialValue(e.target.value)} />
                  <button className={buttonStyle} disabled={pending || !credentialKey || !credentialValue}
                    onClick={() => void manage(credentialKind === 'header' ? 'header_set' : 'env_set', server, credentialKey, credentialValue)}>
                    Save credential
                  </button>
                </div>
              </div>
            )}
          </article>
        ))}
        <p className="text-xs text-text-secondary">These servers are registered in LSM's nested MCP gateway. Their tools are discovered with mcp_tool_search and called through mcp_tool_call. LSM native tools can be disabled independently.</p>
      </div>
    </section>
  );
}
