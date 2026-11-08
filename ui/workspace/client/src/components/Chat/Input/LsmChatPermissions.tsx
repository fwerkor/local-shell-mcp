import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';

type Preferences = { web: boolean; lsm: boolean; mcp: boolean; memory: boolean };
const preferenceKey = (conversationId: string) => ['lsm', 'chat-permissions', conversationId] as const;

export default function LsmChatPermissions({ conversationId }: { conversationId?: string | null }) {
  const client = useQueryClient();
  const available = !!conversationId && conversationId !== 'new';
  const id = conversationId && conversationId !== 'new' ? conversationId : '';
  const query = useQuery<Preferences>({
    queryKey: preferenceKey(id),
    queryFn: () => request.get<Preferences>(`/api/lsm/preferences/${encodeURIComponent(id)}`),
    enabled: available,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const mutation = useMutation<Preferences, Error, { id: string; next: Preferences }>({
    mutationFn: ({ id: requestedId, next }) =>
      request.put(`/api/lsm/preferences/${encodeURIComponent(requestedId)}`, next) as Promise<Preferences>,
    onSuccess: (saved, { id: requestedId }) => {
      client.setQueryData(preferenceKey(requestedId), saved);
    },
  });

  const disabled = !query.data || query.isFetching || mutation.isLoading;
  const update = (field: keyof Preferences, enabled: boolean) => {
    if (!available || disabled || !query.data) return;
    const next = { ...query.data, [field]: enabled };
    if (field === 'lsm' && enabled) next.web = true;
    if (field === 'web' && !enabled) next.lsm = false;
    mutation.mutate({ id, next });
  };

  if (!available) return null;
  return (
    <details className="relative text-xs" aria-label="Conversation permissions">
      <summary className="cursor-pointer rounded-lg border border-border-medium px-2 py-1.5">Permissions</summary>
      <div className="absolute bottom-full right-0 z-50 mb-2 min-w-52 rounded-lg border border-border-medium bg-surface-primary p-3 shadow-lg">
        <strong className="mb-2 block">This conversation</strong>
        {!query.data && !query.isError && <p className="my-2 text-text-secondary">Loading saved permissions…</p>}
        {(['web', 'lsm', 'mcp', 'memory'] as const).map((field) => (
          <label className="my-2 flex cursor-pointer items-center justify-between gap-4" key={field}>
            <span>{field === 'web' ? 'Web search' : field === 'lsm' ? 'LSM tools' : field === 'mcp' ? 'External MCP' : 'Cross-chat memory'}</span>
            <input
              type="checkbox"
              checked={query.data?.[field] ?? false}
              disabled={disabled}
              onChange={(event) => { update(field, event.target.checked); }}
            />
          </label>
        ))}
        <p className="text-text-secondary">External MCP is independent of LSM native tools. It exposes search, inspect and call only; server management stays in the MCP sidebar.</p>
        {query.isError && <p role="alert" className="mt-2 text-status-error">Unable to load chat permissions</p>}
        {mutation.isError && <p role="alert" className="mt-2 text-status-error">Unable to update chat permissions</p>}
      </div>
    </details>
  );
}
