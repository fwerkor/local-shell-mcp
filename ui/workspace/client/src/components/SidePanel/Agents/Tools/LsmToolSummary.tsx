import { Server, Monitor, Settings } from 'lucide-react';
import { useFormContext, useWatch } from 'react-hook-form';
import type { AgentForm } from '~/common';
import { useLocalize } from '~/hooks';

type Access = 'none' | 'read' | 'write';
type MachineSummary = { defaultAccess: Access; overrides: Record<Access, number> };

export function summarizeMachineAccess(
  selected: Record<string, Access> | undefined,
  defaultPermission: Access | undefined,
): MachineSummary | null {
  // Legacy agents select individual native tools, already represented in the list.
  if (selected === undefined && defaultPermission === undefined) return null;
  const defaultAccess = defaultPermission ?? 'write';
  const overrides = { none: 0, read: 0, write: 0 };
  for (const level of Object.values(selected ?? {})) {
    if (level !== defaultAccess) overrides[level]++;
  }
  if (defaultAccess === 'none' && overrides.read === 0 && overrides.write === 0) return null;
  return { defaultAccess, overrides };
}

export function useMachineAccessSummary() {
  const { control } = useFormContext<AgentForm>();
  const selected = useWatch({ control, name: 'machine_permissions' });
  const defaultPermission = useWatch({ control, name: 'machine_default_permission' });
  return summarizeMachineAccess(selected, defaultPermission);
}

function SummaryRow({
  name,
  detail,
  icon: Icon,
  onManage,
}: {
  name: string;
  detail: string;
  icon: typeof Server;
  onManage: () => void;
}) {
  const localize = useLocalize();
  return (
    <li>
      <button
        type="button"
        onClick={onManage}
        className="group flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-surface-secondary focus-visible:ring-2 focus-visible:ring-ring-primary"
        aria-label={name + ' — ' + localize('com_ui_manage')}
      >
        <span
          className="flex size-7 shrink-0 items-center justify-center rounded-md bg-surface-tertiary text-text-secondary"
          aria-hidden="true"
        >
          <Icon className="size-3.5" strokeWidth={1.75} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-text-primary" title={name}>
            {name}
          </span>
          <span className="block text-xs text-text-secondary">{detail}</span>
        </span>
        <Settings className="size-3.5 shrink-0 text-text-secondary" aria-hidden="true" />
      </button>
    </li>
  );
}

export function ExternalMcpSummary({
  server,
  onManage,
}: {
  server: { name: string; tool_count: number };
  onManage: () => void;
}) {
  const localize = useLocalize();
  return (
    <SummaryRow
      name={server.name}
      detail={`MCP · ${server.tool_count} ${localize('com_lsm_external_mcp_tools')}`}
      icon={Server}
      onManage={onManage}
    />
  );
}

export function MachineAccessSummary({
  summary,
  onManage,
}: {
  summary: MachineSummary;
  onManage: () => void;
}) {
  const localize = useLocalize();
  const detail = [
    `${localize('com_lsm_agent_machine_default')}: ${localize(`com_lsm_agent_machine_${summary.defaultAccess}`)}`,
    ...(['read', 'write', 'none'] as const)
      .filter((level) => summary.overrides[level] > 0)
      .map((level) => `${summary.overrides[level]} ${localize(`com_lsm_agent_machine_${level}`)}`),
  ].join(' · ');
  return (
    <SummaryRow
      name={localize('com_lsm_agent_machine_access')}
      detail={detail}
      icon={Monitor}
      onManage={onManage}
    />
  );
}
