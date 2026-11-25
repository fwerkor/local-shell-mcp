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
  const defaultPermission = useWatch({ control, name: 'machine_default_permission' });
  const legacy = selected === undefined && defaultPermission === undefined;
  const inherited = defaultPermission ?? 'write';
  const options = ['none', 'read', 'write'] as const;
  const { data, isLoading, isError } = useLsmMachines();
  const names = useMemo(
    () => [...new Set([
      ...((data || !isLoading) ? ['local'] : []),
      ...(data?.machines ?? []).map((machine) => machine.name),
      ...Object.keys(selected ?? {}),
    ])].sort((a, b) => a === b ? 0 : a === 'local' ? -1 : b === 'local' ? 1 : a.localeCompare(b)),
    [data, selected, isLoading],
  );
  const statuses = new Map((data?.machines ?? []).map((machine) => [machine.name, machine.status]));

  const change = (machine: string, level: Access | 'inherit') => {
    const next = { ...(selected ?? {}) };
    if (level === 'inherit') {
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
              onClick={() => {
                setValue('machine_permissions', {}, { shouldDirty: true, shouldValidate: true });
                setValue('machine_default_permission', 'write', { shouldDirty: true, shouldValidate: true });
              }}>
              {localize('com_lsm_agent_machine_convert')}
            </button>
            <button type="button" className="rounded-md border border-border-medium px-3 py-1.5 text-xs text-text-primary"
              onClick={() => {
                setValue('machine_permissions', {}, { shouldDirty: true, shouldValidate: true });
                setValue('machine_default_permission', 'none', { shouldDirty: true, shouldValidate: true });
              }}>
              {localize('com_lsm_agent_machine_revoke')}
            </button>
          </div>
        </div>
      )}
      {!legacy && (
        <label className="flex items-center justify-between gap-3">
          <span className="min-w-0 text-sm text-text-primary">
            {localize('com_lsm_agent_machine_default')}
            <span className="block text-xs text-text-secondary">
              {localize('com_lsm_agent_machine_default_help')}
            </span>
          </span>
          <select
            aria-label={localize('com_lsm_agent_machine_default')}
            value={inherited}
            onChange={(event) => setValue('machine_default_permission', event.target.value as Access,
              { shouldDirty: true, shouldValidate: true })}
            className="max-w-44 rounded-md border border-border-medium bg-surface-primary p-2 text-sm text-text-primary"
          >
            {options.map((level) => (
              <option key={level} value={level}>{localize(`com_lsm_agent_machine_${level}`)}</option>
            ))}
          </select>
        </label>
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
            value={legacy ? 'legacy' : (selected?.[machine] ?? 'inherit')}
            onChange={(event) => change(machine, event.target.value as Access | 'inherit')}
            disabled={isError || legacy}
            className="max-w-44 rounded-md border border-border-medium bg-surface-primary p-2 text-sm text-text-primary"
          >
            {legacy && <option value="legacy">{localize('com_lsm_agent_machine_legacy_choice')}</option>}
            {!legacy && (
              <option value="inherit">
                {localize('com_lsm_agent_machine_inherit')} ({localize(`com_lsm_agent_machine_${inherited}`)})
              </option>
            )}
            <option value="none">{localize('com_lsm_agent_machine_none')}</option>
            <option value="read">{localize('com_lsm_agent_machine_read')}</option>
            <option value="write">{localize('com_lsm_agent_machine_write')}</option>
          </select>
        </label>
      ))}
    </section>
  );
}
