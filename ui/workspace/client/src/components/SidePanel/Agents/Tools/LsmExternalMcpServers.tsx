import { useQuery } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import { useLocalize } from '~/hooks';

type MCPServer = {
  name: string;
  enabled: boolean;
  transport: string;
  tool_count: number;
};

type MCPServersResponse = { servers: MCPServer[] };

export function useLsmExternalMcpServers() {
  return useQuery<MCPServersResponse>({
    queryKey: ['lsm', 'external-mcp-servers'],
    queryFn: () => request.get('/api/lsm/mcp/servers'),
    retry: false,
    staleTime: 30_000,
  });
}

/** Server discovery is informational: the Agent never receives a fake
 * LibreChat tool id. Runtime uses LSM's nested MCP search/inspect/call tools,
 * gated by the chat's External MCP permission and call approval. */
export default function LsmExternalMcpServers() {
  const localize = useLocalize();
  const { data, isLoading, isError } = useLsmExternalMcpServers();

  return (
    <section aria-label={localize('com_lsm_external_mcp_title')} className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold text-text-primary">
          {localize('com_lsm_external_mcp_title')}
        </h3>
        <p className="mt-1 text-xs text-text-secondary">
          {localize('com_lsm_external_mcp_help')}
        </p>
      </div>
      {isLoading && <p className="text-xs text-text-secondary">{localize('com_lsm_agent_machine_loading')}</p>}
      {isError && <p role="alert" className="text-xs text-status-error">{localize('com_lsm_external_mcp_error')}</p>}
      {!isLoading && !isError && data?.servers.length === 0 && (
        <p className="text-xs text-text-secondary">{localize('com_lsm_external_mcp_empty')}</p>
      )}
      {(data?.servers ?? []).map((server) => (
        <div
          key={server.name}
          className="flex items-center justify-between gap-3 rounded-lg border border-border-light bg-surface-secondary px-3 py-2"
        >
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-text-primary" title={server.name}>
              {server.name}
            </div>
            <div className="text-xs text-text-secondary">
              {server.transport} · {server.tool_count} {localize('com_lsm_external_mcp_tools')}
            </div>
          </div>
          <span className="shrink-0 text-xs text-text-secondary">
            {server.enabled ? localize('com_lsm_external_mcp_enabled') : localize('com_lsm_external_mcp_disabled')}
          </span>
        </div>
      ))}
    </section>
  );
}
