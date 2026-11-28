import { useEffect, useRef, useState } from 'react';
import { Settings2 } from 'lucide-react';
import { TooltipAnchor, PinIcon } from '@librechat/client';
import {
  ArtifactModes,
  Permissions,
  PermissionTypes,
  defaultAgentCapabilities,
} from 'librechat-data-provider';
import { useLocalize, useHasAccess, useAuthContext } from '~/hooks';
import { useBadgeRowContext } from '~/Providers';
import { useGetStartupConfig } from '~/data-provider';
import ToolManagementDialog from '~/components/SidePanel/Agents/Tools/ToolManagementDialog';
import ToolCard from '~/components/SidePanel/Agents/Tools/ToolCard';
import { buildCatalog } from '~/components/SidePanel/Agents/Tools/items/catalog';
import type { AgentItemKind, BuiltinId } from '~/components/SidePanel/Agents/Tools/items/types';
import type { TranslationKeys } from '~/hooks/useLocalize';
import { ExternalMcpServerList } from '~/components/SidePanel/Agents/Tools/LsmExternalMcpServers';
import { useLsmMachines } from '~/components/SidePanel/Agents/Tools/LsmAgentMachineAccess';
import LsmChatPermissions, { useDraftMachinePermissions } from './LsmChatPermissions';

export default function ChatToolManagement({
  showEphemeralTools = true,
  showConversationTools = true,
  conversationId,
  projectId,
  index = 0,
}: {
  showEphemeralTools?: boolean;
  showConversationTools?: boolean;
  conversationId?: string | null;
  projectId?: string | null;
  index?: number;
}) {
  const localize = useLocalize();
  const context = useBadgeRowContext();
  const features = context?.features;
  const { user } = useAuthContext();
  const { data: startupConfig } = useGetStartupConfig();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<AgentItemKind | 'all'>('all');
  const [search, setSearch] = useState('');
  const triggerRef = useRef<HTMLButtonElement>(null);
  const triggerId = `tools-management-button-${index}`;
  useEffect(() => {
    setOpen(false);
    setKind('all');
    setSearch('');
  }, [conversationId, projectId, index]);
  const draft = useDraftMachinePermissions(conversationId, projectId, index);
  const machines = useLsmMachines();
  const canUseWebSearch = useHasAccess({
    permissionType: PermissionTypes.WEB_SEARCH,
    permission: Permissions.USE,
  });
  const canUseMcp = useHasAccess({
    permissionType: PermissionTypes.MCP_SERVERS,
    permission: Permissions.USE,
  });
  const canRunCode = useHasAccess({
    permissionType: PermissionTypes.RUN_CODE,
    permission: Permissions.USE,
  });
  const canUseFileSearch = useHasAccess({
    permissionType: PermissionTypes.FILE_SEARCH,
    permission: Permissions.USE,
  });

  const optedOut = user?.personalization?.memories === false;
  const catalog = buildCatalog({
    agentsConfig: { capabilities: context?.agentsConfig?.capabilities ?? defaultAgentCapabilities },
    regularTools: [],
    mcpServersMap: new Map(),
    skills: [],
    actions: [],
    permissions: {
      webSearch: canUseWebSearch,
      mcp: false,
      skills: false,
      runCode: canRunCode,
      fileSearch: canUseFileSearch,
    },
    showMemory: showConversationTools && startupConfig?.interface?.memories === true && !!features,
  }).filter(
    (item) =>
      item.kind === 'builtin' &&
      (showEphemeralTools || item.id === 'memory' || item.id === 'web_search'),
  );
  const toggles = {
    web_search: context?.webSearch,
    execute_code: context?.codeInterpreter,
    file_search: context?.fileSearch,
    artifacts: context?.artifacts,
    context: undefined,
    memory: undefined,
  };
  function checked(id: BuiltinId) {
    return id === 'memory' ? !optedOut && !!features?.current?.memory : !!toggles[id]?.toggleState;
  }
  function disabled(id: BuiltinId) {
    if (id === 'memory') return optedOut || !features?.canEdit;
    if (id === 'web_search') return !features?.canEdit;
    return !toggles[id];
  }
  function toggle(id: BuiltinId) {
    if (disabled(id)) return;
    if (id === 'memory') features?.toggle('memory', !checked(id));
    else if (id === 'artifacts')
      context?.artifacts.debouncedChange({ value: checked(id) ? '' : ArtifactModes.DEFAULT });
    else toggles[id]?.debouncedChange({ value: !checked(id) });
  }
  const showMachines = showConversationTools;
  const showMcp = canUseMcp && !!features;
  const counts = {
    builtin: catalog.length,
    tool: showMachines ? (machines.data?.machines.length ?? 0) : 0,
    mcp: showMcp ? features.registered.length : 0,
    skill: 0,
    action: 0,
  };
  const term = search.trim().toLowerCase();
  const filtered = catalog.filter(
    (item) =>
      !term ||
      [
        item.name,
        item.description,
        localize(item.name as TranslationKeys),
        localize(item.description as TranslationKeys),
      ].some((value) => value.toLowerCase().includes(term)),
  );

  if (!showConversationTools && catalog.length === 0 && !showMcp) return null;
  return (
    <>
      <TooltipAnchor
        render={
          <button
            type="button"
            ref={triggerRef}
            id={triggerId}
            aria-haspopup="dialog"
            aria-expanded={open}
            aria-label={localize('com_lsm_ui_tool_options')}
            className="flex size-theme-control items-center justify-center rounded-theme-control-round p-1 transition-colors hover:bg-surface-composer-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-text-primary"
            onClick={() => setOpen(true)}
          >
            <Settings2 className="size-5" aria-hidden="true" />
          </button>
        }
        id={triggerId}
        description={localize('com_ui_tools')}
      />
      <ToolManagementDialog
        open={open}
        onOpenChange={setOpen}
        view="marketplace"
        kind={kind}
        onSelectView={() => {}}
        onSelectKind={setKind}
        search={search}
        onSearch={setSearch}
        counts={counts}
        totalCount={counts.builtin + counts.tool + counts.mcp}
        chatMode
        triggerRef={triggerRef}
      >
        {(kind === 'all' || kind === 'builtin') && filtered.length > 0 && (
          <ul className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((item) => {
              if (item.kind !== 'builtin') return null;
              const state = toggles[item.id];
              return (
                <li key={item.id} className="min-w-0">
                  <ToolCard
                    item={item}
                    selected={checked(item.id)}
                    disabled={disabled(item.id)}
                    onToggle={() => toggle(item.id)}
                  />
                  {state?.setIsPinned && (
                    <button
                      type="button"
                      className="mt-1 flex items-center gap-1 rounded px-2 py-1 text-xs text-text-secondary hover:bg-surface-hover"
                      aria-label={
                        localize(state.isPinned ? 'com_ui_unpin' : 'com_ui_pin') +
                        ' ' +
                        localize(item.name as TranslationKeys)
                      }
                      onClick={() => state.setIsPinned(!state.isPinned)}
                    >
                      <span className="size-4">
                        <PinIcon unpin={state.isPinned} />
                      </span>
                      {state.isPinned ? localize('com_ui_unpin') : localize('com_ui_pin')}
                    </button>
                  )}
                  {item.id === 'artifacts' && checked(item.id) && (
                    <select
                      className="mt-1 w-full rounded border border-border-medium bg-surface-primary p-2 text-sm"
                      aria-label={localize('com_ui_artifacts_options')}
                      value={String(state?.toggleState)}
                      onChange={(event) =>
                        context?.artifacts.debouncedChange({ value: event.target.value })
                      }
                    >
                      <option value={ArtifactModes.DEFAULT}>{localize('com_ui_artifacts')}</option>
                      <option value={ArtifactModes.SHADCNUI}>
                        {localize('com_ui_include_shadcnui')}
                      </option>
                      <option value={ArtifactModes.CUSTOM}>
                        {localize('com_ui_custom_prompt_mode')}
                      </option>
                    </select>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {showMachines && (kind === 'all' || kind === 'tool') && (
          <div className="mb-4">
            <LsmChatPermissions
              conversationId={conversationId}
              projectId={projectId}
              draft={draft}
            />
          </div>
        )}
        {showMcp && (kind === 'all' || kind === 'mcp') && (
          <ExternalMcpServerList
            query={features.servers}
            selected={features.selected}
            disabled={!features.canEdit}
            onToggle={features.toggleServer}
            onInherit={features.inheritServers}
            search={search}
            showAgentHelp={false}
          />
        )}
        {features?.isError && (
          <p role="alert" className="mt-2 text-xs text-status-error">
            {localize('com_ui_error_updating_preferences')}
          </p>
        )}
      </ToolManagementDialog>
    </>
  );
}
