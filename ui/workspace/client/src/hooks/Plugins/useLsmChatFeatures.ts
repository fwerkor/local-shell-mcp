import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';

type Features = {
  web: boolean;
  mcp: boolean;
  memory: boolean;
  /** null selects all registered and enabled servers; [] selects none. */
  mcpServers: string[] | null;
};
type Server = { name: string; enabled: boolean; tool_count: number };

export default function useLsmChatFeatures(conversationId?: string | null) {
  const client = useQueryClient();
  const hasChat = !!conversationId && !['new', 'new_conversation'].includes(conversationId);
  const url = hasChat
    ? `/api/lsm/preferences/${encodeURIComponent(conversationId!)}`
    : '/api/lsm/feature-defaults';
  const queryKey = hasChat
    ? ['lsm', 'chat-permissions', conversationId!]
    : ['lsm', 'feature-defaults'];
  const features = useQuery<Features>({ queryKey, queryFn: () => request.get(url), retry: false });
  const servers = useQuery<{ servers: Server[] }>({
    queryKey: ['lsm', 'registered-mcp-servers'],
    queryFn: () => request.get('/api/lsm/mcp/servers'),
    retry: false,
  });
  const mutation = useMutation<
    Features,
    Error,
    {
      url: string;
      queryKey: string[];
      change: Partial<Features>;
    }
  >({
    mutationFn: ({ url, change }) => request.put(url, change),
    onSuccess: (data, { queryKey }) => {
      client.setQueryData<Features>(queryKey, data);
      void client.invalidateQueries(queryKey);
      if (queryKey[1] === 'feature-defaults') {
        void client.invalidateQueries(['lsm', 'chat-permissions']);
      }
    },
  });
  const current = features.data;
  const registered = servers.data?.servers ?? [];
  const selected = current?.mcpServers;
  const canEdit = !!current && !mutation.isLoading;
  const toggle = (name: keyof Pick<Features, 'web' | 'mcp' | 'memory'>, enabled: boolean) => {
    if (canEdit) mutation.mutate({ url, queryKey, change: { [name]: enabled } });
  };
  const toggleServer = (server: string, enabled: boolean) => {
    if (
      !canEdit ||
      !current?.mcp ||
      !registered.some((item) => item.name === server && item.enabled)
    )
      return;
    const all = registered.filter((item) => item.enabled).map((item) => item.name);
    const existing = selected === null ? all : (selected ?? []);
    const next = enabled
      ? [...new Set([...existing, server])]
      : existing.filter((item) => item !== server);
    mutation.mutate({ url, queryKey, change: { mcpServers: next } });
  };
  return {
    current,
    registered,
    canEdit,
    toggle,
    toggleServer,
    isError: features.isError || servers.isError || mutation.isError,
  };
}
