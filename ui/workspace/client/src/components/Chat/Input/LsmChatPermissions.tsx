import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';

type Access = 'none' | 'read' | 'write';
type Scope = 'global' | 'project' | 'chat';
type Flags = { web: boolean; mcp: boolean; memory: boolean };
type Policy = { machines: Record<string, Access>; effective: Record<string, Access> };
type ChatPolicy = Policy & Flags & { lsm: boolean; projectId: string | null };
type Machine = { name: string; status: string };
type Project = { id: string; name: string };

const flags: (keyof Flags)[] = ['web', 'mcp', 'memory'];
const defaults = { web: false, mcp: false, memory: false };

export default function LsmChatPermissions({ conversationId }: { conversationId?: string | null }) {
  const client = useQueryClient();
  const hasChat = !!conversationId && conversationId !== 'new';
  const chatId = hasChat ? conversationId! : '';
  const [scope, setScope] = useState<Scope>(hasChat ? 'chat' : 'global');
  const [projectId, setProjectId] = useState('');
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ right: 8, bottom: 80 });

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
    reposition();
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    return () => {
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [open]);


  const machines = useQuery<{ machines: Machine[] }>({
    queryKey: ['lsm', 'permission-machines'],
    queryFn: () => request.get('/api/lsm/permissions/machines'),
    retry: false,
  });
  const projects = useQuery<{ projects: Project[] }>({
    queryKey: ['lsm', 'permission-projects'],
    queryFn: () => request.get('/api/projects'),
    retry: false,
  });
  const chat = useQuery<ChatPolicy>({
    queryKey: ['lsm', 'chat-permissions', chatId],
    queryFn: () => request.get(`/api/lsm/preferences/${encodeURIComponent(chatId)}`),
    enabled: hasChat,
    retry: false,
  });
  const currentProject = projectId || chat.data?.projectId || '';
  const global = useQuery<Policy>({
    queryKey: ['lsm', 'permission-defaults'],
    queryFn: () => request.get('/api/lsm/permissions/defaults'),
    retry: false,
  });
  const project = useQuery<Policy>({
    queryKey: ['lsm', 'permission-project', currentProject],
    queryFn: () => request.get(`/api/lsm/permissions/projects/${encodeURIComponent(currentProject)}`),
    enabled: !!currentProject,
    retry: false,
  });

  useEffect(() => { if (!hasChat && scope === 'chat') setScope('global'); }, [hasChat, scope]);
  const active: Scope = scope === 'chat' && !hasChat ? 'global' : scope;
  const selected = active === 'global' ? global : active === 'project' ? project : chat;
  const chosenPolicy = selected.data;
  const machineNames = useMemo(() => {
    const known = (machines.data?.machines ?? []).map((machine) => machine.name);
    return [...new Set([
      ...known,
      ...Object.keys(global.data?.machines ?? {}),
      ...Object.keys(project.data?.machines ?? {}),
      ...Object.keys(chat.data?.machines ?? {}),
    ])].sort();
  }, [machines.data, global.data, project.data, chat.data]);
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
  const disabled = mutation.isLoading || selected.isFetching || !chosenPolicy || (active === 'project' && !currentProject);

  function updateMachine(machine: string, access: Access | 'inherit') {
    if (disabled || !chosenPolicy) return;
    const next: Record<string, Access> = { ...chosenPolicy.machines };
    if (access === 'inherit') delete next[machine];
    else next[machine] = access;
    const value = active === 'chat'
      ? { ...defaults, web: chat.data?.web ?? false, mcp: chat.data?.mcp ?? false,
        memory: chat.data?.memory ?? false, machines: next }
      : { machines: next };
    mutation.mutate({ url, value });
  }

  function updateFlag(field: keyof Flags, enabled: boolean) {
    if (!chat.data || mutation.isLoading) return;
    mutation.mutate({
      url: `/api/lsm/preferences/${encodeURIComponent(chatId)}`,
      value: { web: chat.data.web, mcp: chat.data.mcp, memory: chat.data.memory, [field]: enabled,
        machines: chat.data.machines },
    });
  }

  return (
    <>
      <button type="button" ref={trigger} aria-haspopup="dialog" aria-expanded={open}
        className="cursor-pointer rounded-lg border border-border-medium px-2 py-1.5 text-xs"
        onClick={() => setOpen((previous) => !previous)}>Permissions</button>
      {open && createPortal(
      <div role="dialog" aria-label="Machine and conversation permissions"
        style={{ right: position.right, bottom: position.bottom, zIndex: 1000 }}
        className="fixed w-80 max-w-[calc(100vw-16px)] max-h-[65vh] overflow-y-auto rounded-xl border border-border-medium bg-surface-primary p-3 text-xs shadow-xl">
        <strong className="block mb-2 text-sm">Machine access</strong>
        <label className="block mb-2 text-text-secondary">
          Set default permissions or override individual machines in this chat.
        </label>
        <div className="flex gap-1 mb-3">
          {(['global', 'project', 'chat'] as const).map((item) => (
            <button type="button" key={item} disabled={item === 'chat' && !hasChat}
              aria-pressed={active === item}
              className={`flex-1 rounded-md px-2 py-1.5 ${active === item ? 'bg-surface-tertiary font-semibold' : 'hover:bg-surface-secondary'}`}
              onClick={() => setScope(item)}>
              {item === 'global' ? 'Global' : item === 'project' ? 'Project' : 'This chat'}
            </button>
          ))}
        </div>
        {active === 'project' && (
          <select aria-label="Project permission defaults" value={currentProject}
            onChange={(event) => setProjectId(event.target.value)}
            className="mb-3 w-full rounded-md border border-border-medium bg-surface-primary p-2">
            <option value="">Select a project</option>
            {(projects.data?.projects ?? []).map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        )}
        {machineNames.length === 0 && <p className="my-3 text-text-secondary">No machines available.</p>}
        {machineNames.map((machine) => {
          const explicit = chosenPolicy?.machines?.[machine];
          const inherited = chosenPolicy?.effective?.[machine] ?? 'none';
          return (
            <label key={machine} className="my-2 flex items-center justify-between gap-2">
              <span className="min-w-0 truncate" title={machine}>
                {machine}{machine === 'local' && <span className="text-text-secondary"> (controller host)</span>}
              </span>
              <select aria-label={`${machine} machine access`}
                value={explicit ?? (active === 'global' ? 'none' : 'inherit')}
                disabled={disabled} onChange={(event) => updateMachine(machine, event.target.value as Access | 'inherit')}
                className="max-w-44 rounded-md border border-border-medium bg-surface-primary p-1.5">
                {active !== 'global' && <option value="inherit">Inherit ({inherited})</option>}
                <option value="none">No access</option>
                <option value="read">Read only</option>
                <option value="write">Read & write / execute</option>
              </select>
            </label>
          );
        })}
        <p className="mt-2 text-text-secondary">Permissions apply separately to each machine, including local. Read-only permits inspection; read/write also permits commands. Inheritance: Global → Project → This chat. Unknown machines are denied; OAuth scopes still apply.</p>
        {hasChat && active === 'chat' && (
          <div className="mt-3 border-t border-border-medium pt-2">
            {flags.map((field) => (
              <label className="my-2 flex cursor-pointer items-center justify-between gap-3" key={field}>
                <span>{field === 'web' ? 'Web search' : field === 'mcp' ? 'External MCP' : 'Cross-chat memory'}</span>
                <input type="checkbox" checked={chat.data?.[field] ?? false}
                  disabled={!chat.data || mutation.isLoading}
                  onChange={(event) => updateFlag(field, event.target.checked)} />
              </label>
            ))}
          </div>
        )}
        {(selected.isError || machines.isError || projects.isError || mutation.isError) &&
          <p role="alert" className="mt-2 text-status-error">Unable to load or save permissions</p>}
      </div>, document.body)}
    </>
  );
}
