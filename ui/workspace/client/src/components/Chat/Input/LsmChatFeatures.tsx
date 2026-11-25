import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { SlidersHorizontal } from 'lucide-react';
import { request } from 'librechat-data-provider';

type Features = {
  web: boolean;
  mcp: boolean;
  memory: boolean;
  /** null selects all registered and enabled servers; [] selects none. */
  mcpServers: string[] | null;
};
type Server = { name: string; enabled: boolean; tool_count: number };

export default function LsmChatFeatures({ conversationId }: { conversationId?: string | null }) {
  const client = useQueryClient();
  const hasChat = !!conversationId && conversationId !== 'new';
  const url = hasChat
    ? `/api/lsm/preferences/${encodeURIComponent(conversationId!)}`
    : '/api/lsm/feature-defaults';
  const queryKey = hasChat ? ['lsm', 'chat-permissions', conversationId] : ['lsm', 'feature-defaults'];
  const features = useQuery<Features>({ queryKey, queryFn: () => request.get(url), retry: false });
  const servers = useQuery<{ servers: Server[] }>({
    queryKey: ['lsm', 'registered-mcp-servers'],
    queryFn: () => request.get('/api/lsm/mcp/servers'),
    retry: false,
  });
  const mutation = useMutation<Features, Error, Partial<Features>>({
    mutationFn: (change) => request.put(url, change),
    onSuccess: () => void client.invalidateQueries(queryKey),
  });
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ right: 8, bottom: 80 });
  useEffect(() => {
    if (!open) return;
    const reposition = () => {
      const bounds = trigger.current?.getBoundingClientRect();
      if (!bounds) return;
      setPosition({
        right: Math.max(8, window.innerWidth - bounds.right),
        bottom: Math.max(8, window.innerHeight - bounds.top + 8),
      });
    };
    const dismiss = (event: MouseEvent) => {
      if (event.target instanceof Node && !trigger.current?.contains(event.target)
          && !dialog.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    reposition();
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', escape);
    return () => {
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  const current = features.data;
  const registered = servers.data?.servers ?? [];
  const selected = current?.mcpServers;
  const canEdit = !!current && !mutation.isLoading;
  const toggle = (name: keyof Pick<Features, 'web' | 'mcp' | 'memory'>, enabled: boolean) => {
    if (canEdit) mutation.mutate({ [name]: enabled });
  };
  const toggleServer = (server: string, enabled: boolean) => {
    if (!canEdit) return;
    const all = registered.filter((item) => item.enabled).map((item) => item.name);
    const existing = selected === null ? all : (selected ?? []);
    const next = enabled ? [...new Set([...existing, server])] : existing.filter((item) => item !== server);
    mutation.mutate({ mcpServers: next });
  };
  return (
    <>
      <button type="button" ref={trigger} aria-haspopup="dialog" aria-expanded={open}
        aria-label="Tools and features" title="Tools and features"
        className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-border-medium px-2 py-1.5 text-xs text-text-primary hover:bg-surface-secondary"
        onClick={() => setOpen((previous) => !previous)}>
        <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
        <span>Tools</span>
      </button>
      {open && createPortal(
        <div ref={dialog} role="dialog" aria-label="Tools and features"
          style={{ right: position.right, bottom: position.bottom, zIndex: 1000 }}
          className="fixed w-80 max-w-[calc(100vw-16px)] max-h-[65vh] overflow-y-auto rounded-xl border border-border-medium bg-surface-primary p-3 text-sm text-text-primary shadow-xl">
          <strong className="block text-sm">Tools and features</strong>
          <p className="mb-3 mt-1 text-xs text-text-secondary">
            {hasChat ? 'Settings for this conversation' : 'Defaults for new conversations'}
          </p>
          {([
            ['web', 'Web search'],
            ['memory', 'Memory'],
            ['mcp', 'External MCP'],
          ] as const).map(([name, label]) => (
            <label key={name} className="flex cursor-pointer items-center justify-between gap-3 py-2">
              <span>{label}</span>
              <input type="checkbox" aria-label={label}
                checked={current?.[name] ?? false}
                disabled={!canEdit} onChange={(event) => toggle(name, event.target.checked)} />
            </label>
          ))}
          <div className="mt-2 border-t border-border-medium pt-2">
            <strong className="text-xs">Connected MCP servers</strong>
            {registered.length === 0 && !servers.isFetching && (
              <p className="mt-2 text-xs text-text-secondary">No external MCP servers registered.</p>
            )}
            {registered.map((server) => (
              <label key={server.name} className="flex cursor-pointer items-center justify-between gap-3 py-2">
                <span className="min-w-0 truncate text-xs" title={server.name}>
                  {server.name}
                  <span className="ml-1 text-text-secondary">({server.tool_count})</span>
                  {!server.enabled && <span className="ml-1 text-text-secondary">Disabled globally</span>}
                </span>
                <input type="checkbox" aria-label={`MCP server ${server.name}`}
                  checked={server.enabled && (selected === null || selected === undefined || selected.includes(server.name))}
                  disabled={!canEdit || !current?.mcp || !server.enabled || mutation.isLoading}
                  onChange={(event) => toggleServer(server.name, event.target.checked)} />
              </label>
            ))}
            <p className="mt-2 text-xs text-text-secondary">
              {hasChat
                ? 'Server selection applies only to this chat; registrations are unchanged.'
                : 'Selection becomes the default for new chats; registrations are unchanged.'}
            </p>
          </div>
          <p className="mt-3 border-t border-border-medium pt-2 text-xs text-text-secondary">
            LSM shell, files, and jobs follow per-machine access configured in Permissions.
          </p>
          {(features.isError || servers.isError || mutation.isError) && (
            <p role="alert" className="mt-2 text-xs text-status-error">Unable to load or save tool settings.</p>
          )}
        </div>, document.body)}
    </>
  );
}
