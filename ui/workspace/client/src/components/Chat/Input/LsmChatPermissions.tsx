import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, RotateCcw, ShieldCheck, X } from 'lucide-react';
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

function MachineAccessRow({
  machine,
  status,
  explicit,
  inherited,
  canInherit,
  disabled,
  onChange,
}: {
  machine: string;
  status?: string;
  explicit?: Access;
  inherited: Access;
  canInherit: boolean;
  disabled: boolean;
  onChange: (next: Access | 'inherit') => void;
}) {
  const localize = useLocalize();
  const effective = explicit ?? inherited;
  const inheritedLabel = localize(levels.find((level) => level.value === inherited)?.label ?? 'com_lsm_permission_none');
  return (
    <div className="flex min-w-0 items-center justify-between gap-2 rounded-lg py-2">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-text-primary" title={machine}>
          {machine}
        </div>
        <div className="mt-0.5 text-[11px] text-text-secondary">
          {canInherit && explicit === undefined
            ? localize('com_lsm_permission_inherited', { access: inheritedLabel })
            : status === 'offline'
              ? localize('com_lsm_permission_offline')
              : status === 'disabled'
                ? localize('com_lsm_permission_disabled')
                : machine === 'local'
                  ? localize('com_lsm_permission_local')
                  : localize('com_lsm_permission_custom')}
        </div>
      </div>
      <div role="group" aria-label={localize('com_lsm_permission_machine_label', { machine })}
        className="flex shrink-0 items-center gap-0.5 rounded-lg bg-surface-tertiary p-0.5">
        {levels.map(({ value, label }) => (
          <button type="button" key={value}
            aria-label={localize('com_lsm_permission_access_label', { machine, access: localize(label) })}
            aria-pressed={effective === value}
            disabled={disabled}
            onClick={() => onChange(value)}
            className={`min-w-9 rounded-md px-2 py-1.5 text-xs transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-text-primary disabled:opacity-50 ${
              effective === value
                ? 'bg-surface-primary font-semibold text-text-primary shadow-sm'
                : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'
            }`}>
            {localize(label)}
          </button>
        ))}
      </div>
      {canInherit && (
        <button type="button" aria-label={localize('com_lsm_permission_reset_label', { machine })} title={localize('com_lsm_permission_inherit_default')}
          disabled={disabled || explicit === undefined} onClick={() => onChange('inherit')}
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:invisible">
          <RotateCcw size={14} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

/** A UI-only exposure preference. Tokens and OAuth scopes are never modified. */
export default function LsmChatPermissions({
  conversationId,
  projectId = null,
  index = 0,
}: {
  conversationId?: string | null;
  projectId?: string | null;
  index?: number;
}) {
  const localize = useLocalize();
  const client = useQueryClient();
  const hasChat = !!conversationId && !['new', 'new_conversation'].includes(conversationId);
  const chatId = hasChat ? conversationId! : '';
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<Scope>('chat');
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ right: number; top?: number; bottom?: number; maxHeight: number }>({ right: 8, bottom: 8, maxHeight: 0 });
  const draftKey = useMemo(() => ['lsm', 'draft-machine-permissions', index, projectId || ''], [index, projectId]);
  // Keep the draft observed while the composer is mounted so it cannot expire
  // before the first send, even if the permission dialog has been closed.
  const draftQuery = useQuery<Record<string, Access>>({
    queryKey: draftKey,
    enabled: false,
    queryFn: async () => ({}),
  });
  useEffect(() => {
    if (hasChat) return;
    return () => {
      // Reset rather than remove: a mounted observer (including StrictMode's
      // effect replay) must stay attached to the same cache entry.
      if (client.getQueryData(draftKey) !== undefined) client.setQueryData(draftKey, {});
    };
  }, [client, draftKey, hasChat]);

  const chat = useQuery<ChatPolicy>({
    queryKey: ['lsm', 'chat-permissions', chatId],
    queryFn: () => request.get(`/api/lsm/preferences/${encodeURIComponent(chatId)}`),
    enabled: open && hasChat,
    retry: false,
  });
  const associatedProject = (hasChat ? chat.data?.projectId : projectId) ?? '';
  const currentProject = scope === 'project' ? selectedProjectId || associatedProject : associatedProject;
  const machines = useQuery<{ machines: Machine[] }>({
    queryKey: ['lsm', 'permission-machines'],
    queryFn: () => request.get('/api/lsm/permissions/machines'),
    enabled: open,
    retry: false,
  });
  const global = useQuery<Policy>({
    queryKey: ['lsm', 'permission-defaults'],
    queryFn: () => request.get('/api/lsm/permissions/defaults'),
    enabled: open,
    retry: false,
  });
  const projects = useQuery<{ projects: Project[] }>({
    queryKey: ['lsm', 'permission-projects'],
    queryFn: () => request.get('/api/projects'),
    enabled: open && scope === 'project',
    retry: false,
  });
  const project = useQuery<Policy>({
    queryKey: ['lsm', 'permission-project', currentProject],
    queryFn: () => request.get(`/api/lsm/permissions/projects/${encodeURIComponent(currentProject)}`),
    enabled: open && !!currentProject,
    retry: false,
  });

  useEffect(() => {
    setScope('chat');
    setSelectedProjectId('');
    setOpen(false);
  }, [chatId, hasChat, projectId]);

  useLayoutEffect(() => {
    if (!open) return;
    const reposition = () => {
      const bounds = trigger.current?.getBoundingClientRect();
      if (!bounds) return;
      const height = window.innerHeight;
      const above = Math.max(0, bounds.top - 16);
      const below = Math.max(0, height - bounds.bottom - 16);
      const limit = Math.min(650, height * 0.7);
      const width = window.innerWidth;
      const right = Math.min(Math.max(8, width - bounds.right), Math.max(8, width - 384 - 8));
      if (Math.max(above, below) < Math.min(240, limit)) {
        setPosition({ right, top: 8, maxHeight: Math.max(0, height - 16) });
      } else if (above >= below || above >= limit) {
        setPosition({ right, bottom: height - bounds.top + 8, maxHeight: Math.min(limit, above) });
      } else {
        setPosition({ right, top: bounds.bottom + 8, maxHeight: Math.min(limit, below) });
      }
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onOutsideClick = (event: PointerEvent) => {
      if (!panel.current?.contains(event.target as Node) &&
          !trigger.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    reposition();
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    document.addEventListener('keydown', onEscape);
    document.addEventListener('pointerdown', onOutsideClick);
    return () => {
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
      document.removeEventListener('keydown', onEscape);
      document.removeEventListener('pointerdown', onOutsideClick);
    };
  }, [open]);

  const active = scope;
  const isDraft = active === 'chat' && !hasChat;
  const selected = active === 'global' ? global : active === 'project' ? project : chat;
  const explicit = (isDraft ? draftQuery.data : selected.data?.machines) ?? {};
  const inherited: Record<string, Access> = active === 'global'
    ? global.data?.effective ?? {}
    : active === 'project'
      ? global.data?.effective ?? {}
      : associatedProject && currentProject === associatedProject
        ? project.data?.effective ?? global.data?.effective ?? {}
        : global.data?.effective ?? {};
  const machineNames = useMemo(
    () => [...new Set([
      ...(machines.data?.machines ?? []).map((item) => item.name),
      ...Object.keys(explicit),
      ...Object.keys(inherited),
    ])].sort((a, b) => a === 'local' ? -1 : b === 'local' ? 1 : a.localeCompare(b)),
    [machines.data, explicit, inherited],
  );
  const machineStatuses = useMemo(
    () => new Map((machines.data?.machines ?? []).map((item) => [item.name, item.status])),
    [machines.data],
  );

  const mutation = useMutation<Policy | ChatPolicy, Error, { url: string; value: Record<string, unknown> }>({
    mutationFn: ({ url, value }) => request.put(url, value),
    onSuccess: () => {
      void client.invalidateQueries(['lsm', 'permission-defaults']);
      void client.invalidateQueries(['lsm', 'permission-project']);
      void client.invalidateQueries(['lsm', 'chat-permissions']);
    },
  });
  const url = active === 'global' ? '/api/lsm/permissions/defaults'
    : active === 'project' ? `/api/lsm/permissions/projects/${encodeURIComponent(currentProject)}`
      : `/api/lsm/preferences/${encodeURIComponent(chatId)}`;
  const disabled = mutation.isLoading || (isDraft
    ? !global.data || (!!associatedProject && !project.data) || machines.isFetching
    : selected.isFetching || !selected.data || (active === 'project' && !currentProject));

  const saveMachines = (machine: string, access: Access | 'inherit') => {
    if (disabled) return;
    const next = { ...explicit };
    if (access === 'inherit') delete next[machine];
    else next[machine] = access;
    if (isDraft) {
      client.setQueryData(draftKey, next);
      return;
    }
    const value = active === 'chat'
      ? { machines: next, web: chat.data?.web ?? true, mcp: chat.data?.mcp ?? true,
          memory: chat.data?.memory ?? true }
      : { machines: next };
    mutation.mutate({ url, value });
  };

  const projectName = projects.data?.projects.find((item) => item.id === associatedProject)?.name;
  const isUnavailable = selected.isError || machines.isError ||
    (isDraft && (global.isError || (!!associatedProject && project.isError))) ||
    (active === 'project' && (project.isError || projects.isError));

  return (
    <>
      <button type="button" ref={trigger} aria-haspopup="dialog" aria-expanded={open}
        aria-label={localize('com_lsm_permission_tool_permissions')} title={localize('com_lsm_permission_tool_permissions')}
        className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-text-primary ${
          open ? 'bg-surface-hover text-text-primary' : 'text-text-secondary'
        }`}
        onClick={() => setOpen((wasOpen) => !wasOpen)}>
        <ShieldCheck size={15} aria-hidden="true" />
        <span>{localize('com_lsm_permission_permissions')}</span>
        <ChevronDown size={12} aria-hidden="true" className={open ? 'rotate-180' : ''} />
      </button>

      {open && createPortal(
        <div ref={panel} role="dialog" aria-label={localize('com_lsm_permission_tool_permissions')}
          className="lsm-permissions-dialog fixed z-[1000] flex w-96 max-w-[calc(100vw-16px)] flex-col overflow-hidden rounded-2xl border border-border-light bg-surface-primary text-text-primary shadow-xl"
          style={position}>
          <div className="flex shrink-0 items-start justify-between gap-2 px-4 pb-3 pt-4">
            <div>
              <h2 className="text-sm font-semibold">{localize('com_lsm_permission_tool_permissions')}</h2>
              <p className="mt-1 text-xs text-text-secondary">{localize('com_lsm_permission_description')}</p>
            </div>
            <button type="button" aria-label={localize('com_lsm_permission_close')} onClick={() => setOpen(false)}
              className="rounded-md p-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary">
              <X size={16} aria-hidden="true" />
            </button>
          </div>
          <div className="mx-4 flex shrink-0 gap-1 rounded-lg bg-surface-secondary p-1" role="group" aria-label={localize('com_lsm_permission_scope')}>
            {(['chat', 'project', 'global'] as const)
              .map((item) => (
                <button type="button" key={item} aria-pressed={active === item}
                  className={`flex-1 rounded-md px-2 py-2 text-xs transition-colors ${
                    active === item
                      ? 'bg-surface-primary font-semibold text-text-primary shadow-sm'
                      : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'
                  }`}
                  onClick={() => setScope(item)}>
                  {item === 'chat' ? localize('com_lsm_permission_chat') : item === 'project' ? localize('com_lsm_permission_project') : localize('com_lsm_permission_global')}
                </button>
              ))}
          </div>

          <div className="min-h-0 overflow-y-auto px-4 pb-4 pt-3">
            {active === 'project' && (
              associatedProject ? (
                <div className="mb-3 rounded-lg bg-surface-secondary px-3 py-2 text-xs text-text-secondary">
                  {projectName || localize('com_lsm_permission_current_project')}
                </div>
              ) : (
                <label className="mb-3 block text-xs text-text-secondary">
                  {localize('com_lsm_permission_select_project')}
                  <select aria-label={localize('com_lsm_permission_select_project')} value={selectedProjectId}
                    onChange={(event) => setSelectedProjectId(event.target.value)}
                    className="mt-1 w-full rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary">
                    <option value="">{localize('com_lsm_permission_select_project_placeholder')}</option>
                    {(projects.data?.projects ?? []).map((item) =>
                      <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </label>
              )
            )}
            {active === 'project' && !currentProject ? (
              <p className="py-4 text-center text-xs text-text-secondary">{localize('com_lsm_permission_select_project_help')}</p>
            ) : (
              <>
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="text-xs font-semibold text-text-secondary">{localize('com_lsm_permission_machines')}</h3>
                  <span className="text-[11px] text-text-secondary">
                    {active === 'global' ? localize('com_lsm_permission_default_write') : localize('com_lsm_permission_inherit_help')}
                  </span>
                </div>
                {machineNames.length === 0 && !machines.isFetching && (
                  <p className="py-4 text-xs text-text-secondary">{localize('com_lsm_permission_empty')}</p>
                )}
                <div className="divide-y divide-border-light">
                  {machineNames.map((machine) => (
                    <MachineAccessRow key={machine} machine={machine}
                      status={machineStatuses.get(machine)}
                      explicit={explicit[machine]} inherited={inherited[machine] ?? 'none'}
                      canInherit={active !== 'global'} disabled={disabled}
                      onChange={(next) => saveMachines(machine, next)} />
                  ))}
                </div>
              </>
            )}
            {active === 'chat' && hasChat && <ApprovalModeSetting conversationId={chatId} />}
            {isUnavailable || mutation.isError ? (
              <p role="alert" className="mt-2 text-xs text-status-error">{localize('com_lsm_permission_error')}</p>
            ) : null}
            <p className="mt-3 text-[11px] text-text-secondary">
              {active === 'global' ? localize('com_lsm_permission_global_help') :
                active === 'project' ? localize('com_lsm_permission_project_help') :
                  localize('com_lsm_permission_chat_help')}
            </p>
          </div>
        </div>, document.body)}
    </>
  );
}
