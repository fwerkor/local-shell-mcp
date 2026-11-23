import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, RotateCcw, ShieldCheck, X } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';

type Access = 'none' | 'read' | 'write';
type Scope = 'global' | 'project' | 'chat';
type Flags = { web: boolean; mcp: boolean; memory: boolean };
type Policy = { machines: Record<string, Access>; effective: Record<string, Access> };
type ChatPolicy = Policy & Flags & { projectId: string | null };
type Machine = { name: string; status: string };
type Project = { id: string; name: string };

const levels: ReadonlyArray<{ value: Access; label: string }> = [
  { value: 'none', label: '无' },
  { value: 'read', label: '只读' },
  { value: 'write', label: '读写' },
];
const levelName = (value: Access) => levels.find((level) => level.value === value)?.label ?? '无';

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
  const effective = explicit ?? inherited;
  return (
    <div className="flex min-w-0 items-center justify-between gap-2 rounded-lg py-2">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-text-primary" title={machine}>
          {machine}
        </div>
        <div className="mt-0.5 text-[11px] text-text-secondary">
          {canInherit && explicit === undefined
            ? `继承 · ${levelName(inherited)}`
            : status === 'offline'
              ? '离线'
              : status === 'disabled'
                ? '已禁用'
                : machine === 'local'
                  ? '本机'
                  : '自定义'}
        </div>
      </div>
      <div role="group" aria-label={`${machine} 机器权限`}
        className="flex shrink-0 items-center gap-0.5 rounded-lg bg-surface-tertiary p-0.5">
        {levels.map(({ value, label }) => (
          <button type="button" key={value}
            aria-label={`${machine} ${label}`}
            aria-pressed={effective === value}
            disabled={disabled}
            onClick={() => onChange(value)}
            className={`min-w-9 rounded-md px-2 py-1.5 text-xs transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-text-primary disabled:opacity-50 ${
              effective === value
                ? 'bg-surface-primary font-semibold text-text-primary shadow-sm'
                : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'
            }`}>
            {label}
          </button>
        ))}
      </div>
      {canInherit && (
        <button type="button" aria-label={`${machine} 恢复继承`} title="使用上级默认"
          disabled={disabled || explicit === undefined} onClick={() => onChange('inherit')}
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:invisible">
          <RotateCcw size={14} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

const flagLabels: ReadonlyArray<{ key: keyof Flags; label: string }> = [
  { key: 'web', label: '网络搜索' },
  { key: 'mcp', label: '外部 MCP' },
  { key: 'memory', label: '对话记忆' },
];

/** A UI-only exposure preference. Tokens and OAuth scopes are never modified. */
export default function LsmChatPermissions({
  conversationId,
  projectId = null,
}: {
  conversationId?: string | null;
  projectId?: string | null;
}) {
  const client = useQueryClient();
  const hasChat = !!conversationId && !['new', 'new_conversation'].includes(conversationId);
  const chatId = hasChat ? conversationId! : '';
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<Scope>(hasChat ? 'chat' : projectId ? 'project' : 'global');
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ right: 8, bottom: 80 });

  const chat = useQuery<ChatPolicy>({
    queryKey: ['lsm', 'chat-permissions', chatId],
    queryFn: () => request.get(`/api/lsm/preferences/${encodeURIComponent(chatId)}`),
    enabled: open && hasChat,
    retry: false,
  });
  const associatedProject = (hasChat ? chat.data?.projectId : projectId) ?? '';
  const currentProject = selectedProjectId || associatedProject;
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
    setScope(hasChat ? 'chat' : projectId ? 'project' : 'global');
    setSelectedProjectId('');
    setOpen(false);
  }, [chatId, hasChat, projectId]);

  useEffect(() => {
    if (!open) return;
    const reposition = () => {
      const bounds = trigger.current?.getBoundingClientRect();
      if (!bounds) return;
      setPosition({
        right: Math.max(8, window.innerWidth - bounds.right),
        bottom: Math.max(8, window.innerHeight - bounds.top + 8),
      });
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

  const active: Scope = scope === 'chat' && !hasChat ? (projectId ? 'project' : 'global') : scope;
  const selected = active === 'global' ? global : active === 'project' ? project : chat;
  const explicit = selected.data?.machines ?? {};
  const inherited: Record<string, Access> = active === 'global'
    ? {}
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
  const disabled = mutation.isLoading || selected.isFetching || !selected.data ||
    (active === 'project' && !currentProject);

  const saveMachines = (machine: string, access: Access | 'inherit') => {
    if (disabled) return;
    const next = { ...explicit };
    if (access === 'inherit') delete next[machine];
    else next[machine] = access;
    const value = active === 'chat'
      ? { machines: next, web: chat.data?.web ?? false, mcp: chat.data?.mcp ?? false,
          memory: chat.data?.memory ?? false }
      : { machines: next };
    mutation.mutate({ url, value });
  };

  const saveFlag = (field: keyof Flags, enabled: boolean) => {
    if (!chat.data || mutation.isLoading) return;
    mutation.mutate({
      url: `/api/lsm/preferences/${encodeURIComponent(chatId)}`,
      value: { machines: chat.data.machines,
        web: chat.data.web, mcp: chat.data.mcp, memory: chat.data.memory, [field]: enabled },
    });
  };

  const projectName = projects.data?.projects.find((item) => item.id === associatedProject)?.name;
  const isUnavailable = selected.isError || machines.isError ||
    (active === 'project' && (project.isError || projects.isError));

  return (
    <>
      <button type="button" ref={trigger} aria-haspopup="dialog" aria-expanded={open}
        aria-label="工具权限" title="工具权限"
        className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-surface-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-text-primary ${
          open ? 'bg-surface-hover text-text-primary' : 'text-text-secondary'
        }`}
        onClick={() => setOpen((wasOpen) => !wasOpen)}>
        <ShieldCheck size={15} aria-hidden="true" />
        <span>权限</span>
        <ChevronDown size={12} aria-hidden="true" className={open ? 'rotate-180' : ''} />
      </button>

      {open && createPortal(
        <div ref={panel} role="dialog" aria-label="工具权限"
          className="lsm-permissions-dialog fixed z-[1000] flex w-96 max-w-[calc(100vw-16px)] max-h-[min(70vh,650px)] flex-col overflow-hidden rounded-2xl border border-border-light bg-surface-primary text-text-primary shadow-xl"
          style={{ right: position.right, bottom: position.bottom }}>
          <div className="flex shrink-0 items-start justify-between gap-2 px-4 pb-3 pt-4">
            <div>
              <h2 className="text-sm font-semibold">工具权限</h2>
              <p className="mt-1 text-xs text-text-secondary">控制 AI 可以使用哪些机器工具</p>
            </div>
            <button type="button" aria-label="关闭权限设置" onClick={() => setOpen(false)}
              className="rounded-md p-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary">
              <X size={16} aria-hidden="true" />
            </button>
          </div>
          <div className="mx-4 flex shrink-0 gap-1 rounded-lg bg-surface-secondary p-1" role="group" aria-label="权限配置范围">
            {(['chat', 'project', 'global'] as const).filter((item) => item !== 'chat' || hasChat)
              .map((item) => (
                <button type="button" key={item} aria-pressed={active === item}
                  className={`flex-1 rounded-md px-2 py-2 text-xs transition-colors ${
                    active === item
                      ? 'bg-surface-primary font-semibold text-text-primary shadow-sm'
                      : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'
                  }`}
                  onClick={() => setScope(item)}>
                  {item === 'chat' ? '当前会话' : item === 'project' ? '项目默认' : '实例默认'}
                </button>
              ))}
          </div>

          <div className="min-h-0 overflow-y-auto px-4 pb-4 pt-3">
            {active === 'project' && (
              associatedProject ? (
                <div className="mb-3 rounded-lg bg-surface-secondary px-3 py-2 text-xs text-text-secondary">
                  {projectName || '当前所属项目'}
                </div>
              ) : (
                <label className="mb-3 block text-xs text-text-secondary">
                  选择项目
                  <select aria-label="选择项目" value={selectedProjectId}
                    onChange={(event) => setSelectedProjectId(event.target.value)}
                    className="mt-1 w-full rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm text-text-primary">
                    <option value="">选择项目…</option>
                    {(projects.data?.projects ?? []).map((item) =>
                      <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </label>
              )
            )}
            {active === 'project' && !currentProject ? (
              <p className="py-4 text-center text-xs text-text-secondary">选择项目后可设置该项目的默认权限。</p>
            ) : (
              <>
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="text-xs font-semibold text-text-secondary">机器</h3>
                  <span className="text-[11px] text-text-secondary">
                    {active === 'global' ? '默认拒绝' : '未设置时继承上级'}
                  </span>
                </div>
                {machineNames.length === 0 && !machines.isFetching && (
                  <p className="py-4 text-xs text-text-secondary">暂无可配置机器。</p>
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
            {hasChat && active === 'chat' && (
              <div className="mt-3 border-t border-border-light pt-3">
                <h3 className="mb-1 text-xs font-semibold text-text-secondary">其它能力</h3>
                {flagLabels.map(({ key, label }) => (
                  <label key={key} className="flex cursor-pointer items-center justify-between rounded-md py-2 text-sm">
                    <span>{label}</span>
                    <span className="relative inline-flex items-center">
                      <input type="checkbox" className="peer sr-only" aria-label={label}
                        checked={chat.data?.[key] ?? false}
                        disabled={!chat.data || mutation.isLoading}
                        onChange={(event) => saveFlag(key, event.target.checked)} />
                      <span className="h-5 w-9 rounded-full bg-surface-tertiary transition-colors peer-checked:bg-text-primary peer-focus-visible:outline peer-focus-visible:outline-2 peer-disabled:opacity-50" />
                      <span className="pointer-events-none absolute left-0.5 top-0.5 size-4 rounded-full bg-surface-primary shadow-sm transition-transform peer-checked:translate-x-4" />
                    </span>
                  </label>
                ))}
              </div>
            )}
            {isUnavailable || mutation.isError ? (
              <p role="alert" className="mt-2 text-xs text-status-error">权限加载或保存失败，请重试。</p>
            ) : null}
            <p className="mt-3 text-[11px] text-text-secondary">
              {active === 'global' ? '新聊天默认使用此配置。' :
                active === 'project' ? '当前项目的聊天默认继承此配置，可单独覆盖。' :
                  '修改只影响当前聊天，未覆盖的机器自动继承默认权限。'}
            </p>
          </div>
        </div>, document.body)}
    </>
  );
}
