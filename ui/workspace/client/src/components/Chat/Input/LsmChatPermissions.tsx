import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import ApprovalModeSetting from '../approval/ApprovalModeSetting';
import { request } from 'librechat-data-provider';
import useLocalize from '~/hooks/useLocalize';

type Access = 'none' | 'read' | 'write';
type Scope = 'global' | 'project' | 'chat';
type Flags = { web: boolean; mcp: boolean; memory: boolean };
type Policy = { machines: Record<string, Access>; effective: Record<string, Access> };
type ChatPolicy = Policy & Flags & { projectId: string | null };
type Machine = { name: string; status: string };
type Project = { id: string; name: string };

const levels = [
  { value: 'none', label: 'com_lsm_permission_none' },
  { value: 'read', label: 'com_lsm_permission_read' },
  { value: 'write', label: 'com_lsm_permission_write' },
] as const;

const inheritLevel = { value: 'inherit', label: 'com_lsm_permission_inherit' } as const;

function MachineAccessRow({
  machine,
  status,
  explicit,
  inherited,
  canInherit,
  inheritedSource,
  disabled,
  onChange,
}: {
  machine: string;
  status?: string;
  explicit?: Access;
  inherited: Access;
  canInherit: boolean;
  inheritedSource: string;
  disabled: boolean;
  onChange: (next: Access | 'inherit') => void;
}) {
  const localize = useLocalize();
  const selected = explicit ?? (canInherit ? 'inherit' : inherited);
  const inheritedLabel = localize(
    levels.find((level) => level.value === inherited)?.label ?? 'com_lsm_permission_none',
  );
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-lg py-2">
      <div className="min-w-[5rem] flex-1">
        <div className="truncate text-sm font-medium text-text-primary" title={machine}>
          {machine}
        </div>
        <div className="mt-0.5 text-[11px] text-text-secondary">
          {canInherit && explicit === undefined
            ? `${localize('com_lsm_permission_inherited', { access: inheritedLabel })} · ${inheritedSource}`
            : status === 'offline'
              ? localize('com_lsm_permission_offline')
              : status === 'disabled'
                ? localize('com_lsm_permission_disabled')
                : machine === 'local'
                  ? localize('com_lsm_permission_local')
                  : localize('com_lsm_permission_custom')}
        </div>
      </div>
      <div
        role="group"
        aria-label={localize('com_lsm_permission_machine_label', { machine })}
        className="flex max-w-full shrink-0 flex-wrap items-center gap-0.5 rounded-lg bg-surface-tertiary p-0.5"
      >
        {(canInherit ? [inheritLevel, ...levels] : levels).map(({ value, label }) => (
          <button
            type="button"
            key={value}
            aria-label={localize('com_lsm_permission_access_label', {
              machine,
              access: localize(label),
            })}
            aria-pressed={selected === value}
            disabled={disabled}
            onClick={() => onChange(value)}
            className={`min-w-8 rounded-md px-1.5 py-1.5 text-xs transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-text-primary disabled:opacity-50 ${
              selected === value
                ? 'bg-surface-primary font-semibold text-text-primary shadow-sm'
                : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'
            }`}
          >
            {localize(label)}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Keep the unsent draft alive for the lifetime of the composer, not the dialog. */
export function useDraftMachinePermissions(
  conversationId?: string | null,
  projectId?: string | null,
  index = 0,
) {
  const client = useQueryClient();
  const hasChat = !!conversationId && !['new', 'new_conversation'].includes(conversationId);
  const draftKey = useMemo(
    () => ['lsm', 'draft-machine-permissions', index, projectId || ''],
    [index, projectId],
  );
  const draftQuery = useQuery<Record<string, Access>>({
    queryKey: draftKey,
    enabled: false,
    queryFn: async () => ({}),
  });
  useEffect(() => {
    if (hasChat) return;
    return () => {
      if (client.getQueryData(draftKey) !== undefined) client.setQueryData(draftKey, {});
    };
  }, [client, draftKey, hasChat]);
  return { draftKey, draftQuery };
}

export default function LsmChatPermissions({
  conversationId,
  projectId = null,
  draft,
}: {
  conversationId?: string | null;
  projectId?: string | null;
  draft: ReturnType<typeof useDraftMachinePermissions>;
}) {
  const localize = useLocalize();
  const client = useQueryClient();
  const hasChat = !!conversationId && !['new', 'new_conversation'].includes(conversationId);
  const chatId = hasChat ? conversationId! : '';
  const [scope, setScope] = useState<Scope>('chat');
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const { draftKey, draftQuery } = draft;

  const chat = useQuery<ChatPolicy>({
    queryKey: ['lsm', 'chat-permissions', chatId],
    queryFn: () => request.get(`/api/lsm/preferences/${encodeURIComponent(chatId)}`),
    enabled: hasChat,
    retry: false,
  });
  const associatedProject = (hasChat ? chat.data?.projectId : projectId) ?? '';
  const currentProject =
    scope === 'project' ? selectedProjectId || associatedProject : associatedProject;
  const machines = useQuery<{ machines: Machine[] }>({
    queryKey: ['lsm', 'permission-machines'],
    queryFn: () => request.get('/api/lsm/permissions/machines'),
    retry: false,
  });
  const global = useQuery<Policy>({
    queryKey: ['lsm', 'permission-defaults'],
    queryFn: () => request.get('/api/lsm/permissions/defaults'),
    retry: false,
  });
  const projects = useQuery<{ projects: Project[] }>({
    queryKey: ['lsm', 'permission-projects'],
    queryFn: () => request.get('/api/projects'),
    enabled: scope === 'project',
    retry: false,
  });
  const project = useQuery<Policy>({
    queryKey: ['lsm', 'permission-project', currentProject],
    queryFn: () =>
      request.get(`/api/lsm/permissions/projects/${encodeURIComponent(currentProject)}`),
    enabled: !!currentProject,
    retry: false,
  });

  useEffect(() => {
    setScope('chat');
    setSelectedProjectId('');
  }, [chatId, hasChat, projectId]);

  const active = scope;
  const isDraft = active === 'chat' && !hasChat;
  const selected = active === 'global' ? global : active === 'project' ? project : chat;
  const explicit = (isDraft ? draftQuery.data : selected.data?.machines) ?? {};
  const inherited: Record<string, Access> =
    active === 'global'
      ? (global.data?.effective ?? {})
      : active === 'project'
        ? (global.data?.effective ?? {})
        : associatedProject && currentProject === associatedProject
          ? (project.data?.effective ?? global.data?.effective ?? {})
          : (global.data?.effective ?? {});
  const machineNames = useMemo(
    () =>
      [
        ...new Set([
          ...(machines.data?.machines ?? []).map((item) => item.name),
          ...Object.keys(explicit),
          ...Object.keys(inherited),
        ]),
      ].sort((a, b) => (a === 'local' ? -1 : b === 'local' ? 1 : a.localeCompare(b))),
    [machines.data, explicit, inherited],
  );
  const machineStatuses = useMemo(
    () => new Map((machines.data?.machines ?? []).map((item) => [item.name, item.status])),
    [machines.data],
  );

  const mutation = useMutation<
    Policy | ChatPolicy,
    Error,
    { url: string; value: Record<string, unknown> }
  >({
    mutationFn: ({ url, value }) => request.put(url, value),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries(['lsm', 'permission-defaults']),
        client.invalidateQueries(['lsm', 'permission-project']),
        client.invalidateQueries(['lsm', 'chat-permissions']),
      ]);
    },
  });
  const url =
    active === 'global'
      ? '/api/lsm/permissions/defaults'
      : active === 'project'
        ? `/api/lsm/permissions/projects/${encodeURIComponent(currentProject)}`
        : `/api/lsm/preferences/${encodeURIComponent(chatId)}`;
  const parentReady =
    !!global.data &&
    !global.isFetching &&
    (active !== 'chat' || !associatedProject || (!!project.data && !project.isFetching));
  const disabled =
    mutation.isLoading ||
    machines.isFetching ||
    !parentReady ||
    (!isDraft && (selected.isFetching || !selected.data)) ||
    (active === 'project' && !currentProject);

  const savePolicy = (next: Record<string, Access>) => {
    if (disabled) return;
    if (isDraft) {
      client.setQueryData(draftKey, next);
      return;
    }
    mutation.mutate({ url, value: { machines: next } });
  };

  const saveMachines = (machine: string, access: Access | 'inherit') => {
    if (access === (explicit[machine] ?? (active === 'global' ? inherited[machine] : 'inherit')))
      return;
    const next = { ...explicit };
    if (access === 'inherit') delete next[machine];
    else next[machine] = access;
    savePolicy(next);
  };

  const projectName = projects.data?.projects.find((item) => item.id === associatedProject)?.name;
  const isUnavailable =
    selected.isError ||
    machines.isError ||
    global.isError ||
    (active === 'chat' && !!associatedProject && project.isError) ||
    (active === 'project' && (project.isError || projects.isError));

  return (
    <section aria-label={localize('com_lsm_permission_tool_permissions')} className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">{localize('com_lsm_permission_tool_permissions')}</h3>
        <p className="mt-1 text-xs text-text-secondary">
          {localize('com_lsm_permission_description')}
        </p>
      </div>
      <div
        className="flex shrink-0 gap-1 rounded-lg bg-surface-secondary p-1"
        role="group"
        aria-label={localize('com_lsm_permission_scope')}
      >
        {(['chat', 'project', 'global'] as const).map((item) => (
          <button
            type="button"
            key={item}
            aria-pressed={active === item}
            className={`flex-1 rounded-md px-2 py-2 text-xs transition-colors ${
              active === item
                ? 'bg-surface-primary font-semibold text-text-primary shadow-sm'
                : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'
            }`}
            onClick={() => setScope(item)}
          >
            {item === 'chat'
              ? localize('com_lsm_permission_chat')
              : item === 'project'
                ? localize('com_lsm_permission_project')
                : localize('com_lsm_permission_global')}
          </button>
        ))}
      </div>

      <div className="min-h-0">
        {active === 'project' &&
          (associatedProject ? (
            <div className="mb-3 rounded-lg bg-surface-secondary px-3 py-2 text-xs text-text-secondary">
              {projectName || localize('com_lsm_permission_current_project')}
            </div>
          ) : (
            <label className="mb-3 block text-xs text-text-secondary">
              {localize('com_lsm_permission_select_project')}
              <select
                aria-label={localize('com_lsm_permission_select_project')}
                value={selectedProjectId}
                onChange={(event) => setSelectedProjectId(event.target.value)}
                className="mt-1 w-full rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary"
              >
                <option value="">
                  {localize('com_lsm_permission_select_project_placeholder')}
                </option>
                {(projects.data?.projects ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        {active === 'project' && !currentProject ? (
          <p className="py-4 text-center text-xs text-text-secondary">
            {localize('com_lsm_permission_select_project_help')}
          </p>
        ) : (
          <>
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-xs font-semibold text-text-secondary">
                {localize('com_lsm_permission_machines')}
              </h3>
              {active === 'global' ? (
                <span className="text-[11px] text-text-secondary">
                  {localize('com_lsm_permission_default_write')}
                </span>
              ) : (
                <button
                  type="button"
                  disabled={disabled || Object.keys(explicit).length === 0}
                  onClick={() => savePolicy({})}
                  className="rounded px-1.5 py-1 text-xs text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:opacity-50"
                >
                  {localize('com_lsm_permission_reset_all')}
                </button>
              )}
            </div>
            {machineNames.length === 0 && !machines.isFetching && (
              <p className="py-4 text-xs text-text-secondary">
                {localize('com_lsm_permission_empty')}
              </p>
            )}
            <div className="divide-y divide-border-light">
              {machineNames.map((machine) => (
                <MachineAccessRow
                  key={machine}
                  machine={machine}
                  status={machineStatuses.get(machine)}
                  explicit={explicit[machine]}
                  inherited={inherited[machine] ?? 'none'}
                  canInherit={active !== 'global'}
                  disabled={disabled}
                  inheritedSource={localize(
                    active === 'chat' &&
                      associatedProject &&
                      project.data?.machines[machine] !== undefined
                      ? 'com_lsm_permission_project'
                      : 'com_lsm_permission_global',
                  )}
                  onChange={(next) => saveMachines(machine, next)}
                />
              ))}
            </div>
          </>
        )}
        {active === 'chat' && hasChat && <ApprovalModeSetting conversationId={chatId} />}
        {isUnavailable || mutation.isError ? (
          <p role="alert" className="mt-2 text-xs text-status-error">
            {localize('com_lsm_permission_error')}
          </p>
        ) : null}
        <p className="mt-3 text-[11px] text-text-secondary">
          {active === 'global'
            ? localize('com_lsm_permission_global_help')
            : active === 'project'
              ? localize('com_lsm_permission_project_help')
              : localize('com_lsm_permission_chat_help')}
        </p>
      </div>
    </section>
  );
}
