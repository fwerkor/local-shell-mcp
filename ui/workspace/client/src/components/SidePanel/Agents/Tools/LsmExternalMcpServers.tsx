import { useFormContext, useWatch } from 'react-hook-form';
import type { AgentForm } from '~/common';
import { useLocalize } from '~/hooks';

import { useLsmExternalMcpServers, type MCPServer } from '~/hooks/Plugins/useLsmExternalMcpServers';
export { useLsmExternalMcpServers };

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
  const query = useLsmExternalMcpServers();
  const { control, setValue } = useFormContext<AgentForm>();
  const selected = useWatch({ control, name: 'mcp_servers' });

  function toggle(name: string, enabled: boolean) {
    const next = new Set(
      selected ?? (query.data?.servers ?? []).filter((s) => s.enabled).map((s) => s.name),
    );
    if (enabled) next.add(name);
    else next.delete(name);
    setValue('mcp_servers', [...next].sort(), { shouldDirty: true, shouldValidate: true });
  }

  return (
    <ExternalMcpServerList
      query={query}
      selected={selected}
      onToggle={toggle}
      onInherit={() => setValue('mcp_servers', null, { shouldDirty: true, shouldValidate: true })}
    />
  );
}

export function ExternalMcpServerList({
  query,
  selected,
  onToggle,
  onInherit,
  disabled = false,
  search = '',
  showAgentHelp = true,
}: {
  query: ReturnType<typeof useLsmExternalMcpServers>;
  selected: string[] | null | undefined;
  onToggle: (name: string, enabled: boolean) => void;
  onInherit: () => void;
  disabled?: boolean;
  search?: string;
  showAgentHelp?: boolean;
}) {
  const localize = useLocalize();
  const { data, isLoading, isError } = query;
  return (
    <section aria-label={localize('com_lsm_external_mcp_title')} className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold text-text-primary">
          {localize('com_lsm_external_mcp_title')}
        </h3>
        {showAgentHelp && (
          <p className="mt-1 text-xs text-text-secondary">
            {localize('com_lsm_external_mcp_help')}
          </p>
        )}
      </div>
      {selected !== null && (
        <button
          type="button"
          className="text-xs text-text-secondary underline"
          disabled={disabled || isError || isLoading}
          onClick={onInherit}
        >
          {localize('com_lsm_external_mcp_inherit')}
        </button>
      )}
      {isLoading && (
        <p className="text-xs text-text-secondary">{localize('com_lsm_agent_machine_loading')}</p>
      )}
      {isError && (
        <p role="alert" className="text-xs text-status-error">
          {localize('com_lsm_external_mcp_error')}
        </p>
      )}
      {!isLoading && !isError && data?.servers.length === 0 && (
        <p className="text-xs text-text-secondary">{localize('com_lsm_external_mcp_empty')}</p>
      )}
      {(data?.servers ?? [])
        .filter((server) => server.name.toLowerCase().includes(search.toLowerCase()))
        .map((server) => (
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
                disabled={disabled || !server.enabled || isError}
                onChange={(event) => onToggle(server.name, event.target.checked)}
              />
              {localize(
                isExternalMcpSelected(server, selected)
                  ? 'com_lsm_external_mcp_enabled'
                  : 'com_lsm_external_mcp_disabled',
              )}
            </label>
          </div>
        ))}
    </section>
  );
}
