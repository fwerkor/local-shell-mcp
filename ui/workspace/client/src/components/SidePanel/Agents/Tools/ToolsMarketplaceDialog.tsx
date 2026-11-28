import { useState, useMemo, useCallback } from 'react';
import { useFormContext } from 'react-hook-form';
import { AgentCapabilities, removeCodeExecutionCaller } from 'librechat-data-provider';
import { useToastContext } from '@librechat/client';
import type { AgentItem, AgentItemKind, ItemFilter } from './items/types';
import type { CapabilityFileCounts } from './items/capabilities';
import type { AgentForm } from '~/common';
import {
  itemKey,
  mcpAllToken,
  mcpServerToken,
  matchesMcpServer,
  mcpServerIds,
} from './items/selectors';
import { useAgentFileEntries, useAgentItems, useUninstallToolCredentials } from './hooks';
import ToolManagementDialog from './ToolManagementDialog';
import { requiresFileManagerRemoval } from './items/capabilities';
import AddMcpServerDialog from './ItemDialog/AddMcpServerDialog';
import { computeToggleAction } from './items/mutations';
import { useLocalize, useToolFavorites } from '~/hooks';
import MarketplaceCatalog from './MarketplaceCatalog';
import ItemDialog from './ItemDialog/ItemDialog';
import { applyFilter } from './items/filtering';
import { NEW_ACTION_ID } from './items/types';
import { isEphemeralAgent } from '~/common';
import LsmExternalMcpServers, { useLsmExternalMcpServers } from './LsmExternalMcpServers';
import LsmAgentMachineAccess, { useLsmMachines } from './LsmAgentMachineAccess';

interface ToolsMarketplaceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: string;
  initialKind?: Kind;
}

type View = NonNullable<ItemFilter['view']>;
type Kind = AgentItemKind | 'all';

export default function ToolsMarketplaceDialog({
  open,
  onOpenChange,
  agentId,
  initialKind = 'all',
}: ToolsMarketplaceDialogProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const { getValues, setValue } = useFormContext<AgentForm>();
  const uninstallToolCredentials = useUninstallToolCredentials();

  /** Skills are excluded here — they have their own picker (`SkillsDialog`). */
  const { catalog, selected: selectedItems } = useAgentItems({ agentId });
  const externalMcpServers = useLsmExternalMcpServers();
  const lsmMachines = useLsmMachines();

  const { favoriteKeys, toggle: toggleFavorite } = useToolFavorites();

  const [view, setView] = useState<View>('marketplace');
  const [kind, setKind] = useState<Kind>(initialKind);
  const [search, setSearch] = useState('');
  const [detailItem, setDetailItem] = useState<AgentItem | null>(null);
  const [addMcpOpen, setAddMcpOpen] = useState(false);

  const handleCreateNew = useCallback(
    (createKind: 'mcp' | 'action') => {
      if (createKind === 'mcp') {
        setAddMcpOpen(true);
        return;
      }
      /** Actions are persisted against the agent id, so an unsaved agent has
       * nothing to attach them to — surface the save-first error instead of
       * letting the editor fail on submit. */
      if (isEphemeralAgent(agentId)) {
        showToast({ message: localize('com_agents_no_agent_id_error'), status: 'error' });
        return;
      }
      setDetailItem({
        kind: 'action',
        id: NEW_ACTION_ID,
        name: localize('com_ui_new_action'),
        description: '',
        iconKey: 'action',
        endpointCount: 0,
      });
    },
    [agentId, localize, showToast],
  );

  const selectedIds = useMemo(() => new Set(selectedItems.map(itemKey)), [selectedItems]);
  const { knowledgeFiles, codeFiles } = useAgentFileEntries();
  const fileCounts: CapabilityFileCounts = useMemo(
    () => ({ knowledge_files: knowledgeFiles.length, code_files: codeFiles.length }),
    [knowledgeFiles, codeFiles],
  );

  const counts = useMemo(
    () => ({
      builtin: catalog.filter((i) => i.kind === 'builtin').length,
      tool:
        catalog.filter((i) => i.kind === 'tool').length + (lsmMachines.data?.machines.length ?? 0),
      mcp:
        catalog.filter((i) => i.kind === 'mcp').length +
        (externalMcpServers.data?.servers.length ?? 0),
      skill: 0,
      action: catalog.filter((i) => i.kind === 'action').length,
    }),
    [catalog, externalMcpServers.data, lsmMachines.data],
  );

  const filtered = useMemo(
    () =>
      applyFilter(catalog, { search, kind, category: 'all', view }, { favoritedIds: favoriteKeys }),
    [catalog, search, kind, view, favoriteKeys],
  );

  const handleToggle = useCallback(
    (item: AgentItem) => {
      const selected = selectedIds.has(itemKey(item));
      /** A file-backed built-in cannot be switched off by its flag while it holds
       * files — the row would stay selected and the save would disagree with it — so
       * send the user to the dialog that manages those files, as the tools list does. */
      if (selected && item.kind === 'builtin' && requiresFileManagerRemoval(item.id, fileCounts)) {
        setDetailItem(item);
        return;
      }
      const patch = computeToggleAction(item, { selected });
      switch (patch.type) {
        case 'builtin':
          setValue(patch.field as keyof AgentForm, patch.value as never, { shouldDirty: true });
          if (patch.field === AgentCapabilities.execute_code && patch.value === false) {
            setValue('tool_options', removeCodeExecutionCaller(getValues('tool_options')), {
              shouldDirty: true,
            });
          }
          break;
        case 'tool-add': {
          const current = (getValues('tools') ?? []) as string[];
          setValue('tools', Array.from(new Set([...current, patch.id])), { shouldDirty: true });
          break;
        }
        case 'tool-remove': {
          const current = (getValues('tools') ?? []) as string[];
          setValue(
            'tools',
            current.filter((t) => t !== patch.id),
            { shouldDirty: true },
          );
          uninstallToolCredentials(patch.id);
          break;
        }
        case 'mcp-add': {
          if (item.kind !== 'mcp') break;
          const toolIds =
            item.server.requestScoped || !item.server.tools?.length
              ? [mcpAllToken(item.id)]
              : (item.server.tools ?? []).map((t) => t.tool_id);
          const current = (getValues('tools') ?? []) as string[];
          setValue(
            'tools',
            Array.from(new Set([...current, mcpServerToken(item.id), ...toolIds])),
            { shouldDirty: true },
          );
          break;
        }
        case 'mcp-remove': {
          if (item.kind !== 'mcp') break;
          const toolIds = new Set((item.server.tools ?? []).map((t) => t.tool_id));
          const allServerNames = mcpServerIds(catalog);
          const current = (getValues('tools') ?? []) as string[];
          setValue(
            'tools',
            current.filter((t) => !matchesMcpServer(t, item.id, allServerNames) && !toolIds.has(t)),
            { shouldDirty: true },
          );
          break;
        }
        default:
          break;
      }
    },
    [getValues, setValue, selectedIds, uninstallToolCredentials, catalog, fileCounts],
  );

  const handleCardClick = useCallback(
    (item: AgentItem) => {
      /** Actions have no simple enable toggle — clicking always opens the editor. */
      if (item.kind === 'action') {
        setDetailItem(item);
        return;
      }
      if (item.kind === 'builtin' && item.id === 'context') {
        setDetailItem(item);
        return;
      }
      const wasSelected = selectedIds.has(itemKey(item));
      /** Ready servers can resolve their tools with user credentials at runtime,
       * even when the instance catalog is empty. Unready servers still need setup;
       * a selected toolless server must remain removable. */
      if (
        item.kind === 'mcp' &&
        item.toolCount === 0 &&
        !wasSelected &&
        !(item.server.isReadyForAgent ?? item.server.isConnected)
      ) {
        setDetailItem(item);
        return;
      }
      if (!wasSelected && item.status === 'needs_setup') {
        setDetailItem(item);
        return;
      }
      handleToggle(item);
    },
    [handleToggle, selectedIds],
  );

  const handleConfigure = useCallback((item: AgentItem) => {
    setDetailItem(item);
  }, []);

  return (
    <ToolManagementDialog
      open={open}
      onOpenChange={onOpenChange}
      view={view}
      kind={kind}
      onSelectView={setView}
      onSelectKind={setKind}
      search={search}
      onSearch={setSearch}
      counts={counts}
      totalCount={
        catalog.length +
        (externalMcpServers.data?.servers.length ?? 0) +
        (lsmMachines.data?.machines.length ?? 0)
      }
      onCreateNew={handleCreateNew}
      dialogs={
        <>
          <ItemDialog item={detailItem} agentId={agentId} onClose={() => setDetailItem(null)} />
          <AddMcpServerDialog open={addMcpOpen} onOpenChange={setAddMcpOpen} />
        </>
      }
    >
      {(kind === 'tool' || kind === 'all') && view === 'marketplace' && (
        <div className="mb-4">
          <LsmAgentMachineAccess />
        </div>
      )}
      {(kind === 'mcp' || kind === 'all') && view === 'marketplace' && (
        <div className="mb-4">
          <LsmExternalMcpServers />
        </div>
      )}
      {(filtered.length > 0 ||
        view !== 'marketplace' ||
        !(
          (kind === 'tool' && (lsmMachines.data?.machines.length ?? 0) > 0) ||
          (kind === 'mcp' && (externalMcpServers.data?.servers.length ?? 0) > 0) ||
          (kind === 'all' &&
            ((lsmMachines.data?.machines.length ?? 0) > 0 ||
              (externalMcpServers.data?.servers.length ?? 0) > 0))
        )) && (
        <MarketplaceCatalog
          items={filtered}
          selectedIds={selectedIds}
          onToggle={handleCardClick}
          onConfigure={handleConfigure}
          view={view}
          favoriteKeys={favoriteKeys}
          onToggleFavorite={toggleFavorite}
        />
      )}
    </ToolManagementDialog>
  );
}
