import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useFormContext, useWatch } from 'react-hook-form';
import { request } from 'librechat-data-provider';
import type { AgentForm } from '~/common';
import { useLocalize } from '~/hooks';

type Access = 'none' | 'read' | 'write';
type Machine = { name: string; status: string };
type MachineResponse = { machines: Machine[] };

export function useLsmMachines() {
  return useQuery<MachineResponse>({
    queryKey: ['lsm', 'permission-machines'],
    queryFn: () => request.get('/api/lsm/permissions/machines'),
    retry: false,
  });
}

/**
 * Native LSM tools are exposed by machine, not selected one by one.
 * These grants are an Agent-level ceiling: the execution path still requires
 * the current conversation's inherited Global → Project → Chat permission.
 */
export default function LsmAgentMachineAccess() {
  const localize = useLocalize();
  const { control, setValue } = useFormContext<AgentForm>();
  const selected = useWatch({ control, name: 'machine_permissions' });
  const legacy = selected === undefined;
  const { data, isLoading, isError } = useLsmMachines();
  const names = useMemo(
    () => [...new Set([
      ...(data?.machines ?? []).map((machine) => machine.name),
      ...Object.keys(selected ?? {}),
    ])].sort(),
    [data, selected],
  );
  const statuses = new Map((data?.machines ?? []).map((machine) => [machine.name, machine.status]));

  const change = (machine: string, level: Access) => {
    const next = { ...(selected ?? {}) };
    if (level === 'write') {
      delete next[machine];
    } else {
      next[machine] = level;
    }
    setValue('machine_permissions', next, { shouldDirty: true, shouldValidate: true });
  };

  return (
    <section aria-label={localize('com_lsm_agent_machine_access')} className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-text-primary">
          {localize('com_lsm_agent_machine_access')}
        </h3>
        <p className="mt-1 text-xs text-text-secondary">
          {localize('com_lsm_agent_machine_help')}
        </p>
      </div>
      {legacy && (
        <div className="space-y-2 rounded-md border border-border-medium p-3">
          <p className="text-xs text-text-secondary">
            {localize('com_lsm_agent_machine_legacy')}
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="rounded-md border border-border-medium px-3 py-1.5 text-xs text-text-primary"
              onClick={() => setValue('machine_permissions', {}, { shouldDirty: true, shouldValidate: true })}>
              {localize('com_lsm_agent_machine_convert')}
            </button>
            <button type="button" className="rounded-md border border-border-medium px-3 py-1.5 text-xs text-text-primary"
              disabled={isLoading || isError || names.length === 0}
              onClick={() => setValue('machine_permissions', Object.fromEntries(names.map((name) => [name, 'none' as Access])),
                { shouldDirty: true, shouldValidate: true })}>
              {localize('com_lsm_agent_machine_revoke')}
            </button>
          </div>
        </div>
      )}
      {isLoading && <p className="text-xs text-text-secondary">{localize('com_lsm_agent_machine_loading')}</p>}
      {isError && <p role="alert" className="text-xs text-status-error">{localize('com_lsm_agent_machine_error')}</p>}
      {!isLoading && !isError && names.length === 0 && (
        <p className="text-xs text-text-secondary">{localize('com_lsm_agent_machine_empty')}</p>
      )}
      {names.map((machine) => (
        <label key={machine} className="flex items-center justify-between gap-3">
          <span className="min-w-0 truncate text-sm text-text-primary" title={machine}>
            {machine}
            {statuses.get(machine) === 'disabled' && (
              <span className="ml-2 text-xs text-text-secondary">
                ({localize('com_lsm_agent_machine_disabled')})
              </span>
            )}
          </span>
          <select
            aria-label={`${machine} machine access`}
            value={legacy ? 'legacy' : (selected?.[machine] ?? 'write')}
            onChange={(event) => change(machine, event.target.value as Access)}
            disabled={isError || legacy}
            className="max-w-44 rounded-md border border-border-medium bg-surface-primary p-2 text-sm text-text-primary"
          >
            {legacy && <option value="legacy">{localize('com_lsm_agent_machine_legacy_choice')}</option>}
            <option value="none">{localize('com_lsm_agent_machine_none')}</option>
            <option value="read">{localize('com_lsm_agent_machine_read')}</option>
            <option value="write">{localize('com_lsm_agent_machine_write')}</option>
          </select>
        </label>
      ))}
    </section>
  );
}
