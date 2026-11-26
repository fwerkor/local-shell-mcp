import { useQuery } from '@tanstack/react-query';
import { useFormContext, useWatch } from 'react-hook-form';
import type { AgentForm } from '~/common';
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

export function isExternalMcpSelected(server: MCPServer, selected: string[] | null | undefined) {
  return server.enabled && (selected == null || selected.includes(server.name));
}

export function useSelectedExternalMcpServers() {
  const { control } = useFormContext<AgentForm>();
  const selected = useWatch({ control, name: 'mcp_servers' });
  const { data } = useLsmExternalMcpServers();
  return (data?.servers ?? []).filter((server) => isExternalMcpSelected(server, selected));
}

export default function LsmExternalMcpServers() {
  const localize = useLocalize();
  const { data, isLoading, isError } = useLsmExternalMcpServers();
  const { control, setValue } = useFormContext<AgentForm>();
  const selected = useWatch({ control, name: 'mcp_servers' });

  function toggle(name: string, enabled: boolean) {
    const next = new Set(selected ?? (data?.servers ?? []).filter((s) => s.enabled).map((s) => s.name));
    if (enabled) next.add(name);
    else next.delete(name);
    setValue('mcp_servers', [...next].sort(), { shouldDirty: true, shouldValidate: true });
  }

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
      {selected !== null && (
        <button type="button" className="text-xs text-text-secondary underline"
          onClick={() => setValue('mcp_servers', null, { shouldDirty: true, shouldValidate: true })}>
          {localize('com_lsm_external_mcp_inherit')}
        </button>
      )}
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
          <label className="flex shrink-0 items-center gap-2 text-xs text-text-secondary">
            <input
              type="checkbox"
              aria-label={server.name}
              checked={isExternalMcpSelected(server, selected)}
              disabled={!server.enabled || isError}
              onChange={(event) => toggle(server.name, event.target.checked)}
            />
            {localize(isExternalMcpSelected(server, selected)
              ? 'com_lsm_external_mcp_enabled' : 'com_lsm_external_mcp_disabled')}
          </label>
        </div>
      ))}
    </section>
  );
}
