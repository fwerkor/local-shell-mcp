import { useMemo, useState } from 'react';
import { Plus } from 'lucide-react';
import { matchSorter } from 'match-sorter';
import { PermissionTypes, Permissions } from 'librechat-data-provider';
import { Button, Dropdown, FilterInput, TooltipAnchor, OGDialogTrigger } from '@librechat/client';
import type { TUserMemory } from 'librechat-data-provider';
import { useMemoriesQuery } from '~/data-provider';
import { useLocalize, useHasAccess } from '~/hooks';
import { PanelContent } from '~/components/ui';
import MemoryCardSkeleton from './MemoryCardSkeleton';
import MemoryCreateDialog from './MemoryCreateDialog';
import MemoryUsageBadge from './MemoryUsageBadge';
import MemoryList from './MemoryList';

/** Partition filter sentinels; any other value is an agent id */
const PARTITION_ALL = 'all';
const PARTITION_PERSONAL = 'personal';

export default function MemoryPanel() {
  const localize = useLocalize();
  const [searchQuery, setSearchQuery] = useState('');
  const [partitionFilter, setPartitionFilter] = useState(PARTITION_ALL);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const hasReadAccess = useHasAccess({
    permissionType: PermissionTypes.MEMORIES,
    permission: Permissions.READ,
  });

  // The panel may be open while another chat, tab or scheduled agent writes.
  const { data: memData, isLoading } = useMemoriesQuery({
    enabled: hasReadAccess,
    refetchInterval: 15000,
    refetchIntervalInBackground: false,
  });

  const hasUpdateAccess = useHasAccess({
    permissionType: PermissionTypes.MEMORIES,
    permission: Permissions.UPDATE,
  });

  const hasCreateAccess = useHasAccess({
    permissionType: PermissionTypes.MEMORIES,
    permission: Permissions.CREATE,
  });

  const memories: TUserMemory[] = useMemo(() => memData?.memories ?? [], [memData]);

  const partitionOptions = useMemo(() => {
    const agentsById = new Map<string, string>();
    for (const memory of memories) {
      if (memory.agentId != null && !agentsById.has(memory.agentId)) {
        agentsById.set(memory.agentId, memory.agentName ?? memory.agentId);
      }
    }
    if (agentsById.size === 0) {
      return null;
    }
    return [
      { value: PARTITION_ALL, label: localize('com_ui_memories_all') },
      { value: PARTITION_PERSONAL, label: localize('com_ui_memories_personal') },
      ...[...agentsById.entries()].map(([value, label]) => ({ value, label })),
    ];
  }, [memories, localize]);

  /** Falls back to "all" when the selected partition no longer exists
   *  (e.g. the last memory of that agent was deleted), so the panel never
   *  gets stuck filtering on a removed partition. */
  const activePartition = useMemo(() => {
    if (partitionFilter === PARTITION_ALL || partitionFilter === PARTITION_PERSONAL) {
      return partitionFilter;
    }
    return partitionOptions?.some((option) => option.value === partitionFilter)
      ? partitionFilter
      : PARTITION_ALL;
  }, [partitionOptions, partitionFilter]);

  const filteredMemories = useMemo(() => {
    const partitionMemories =
      activePartition === PARTITION_ALL
        ? memories
        : memories.filter((memory) =>
            activePartition === PARTITION_PERSONAL
              ? memory.agentId == null
              : memory.agentId === activePartition,
          );
    return matchSorter(partitionMemories, searchQuery, {
      keys: ['key', 'value'],
    });
  }, [memories, searchQuery, activePartition]);

  if (!hasReadAccess) {
    return (
      <div className="flex h-full w-full items-center justify-center p-4">
        <div className="text-center">
          <p className="text-sm text-text-secondary">{localize('com_ui_no_read_access')}</p>
        </div>
      </div>
    );
  }

  const tokenLimit = memData?.tokenLimit ?? null;
  const showUsageBadge = tokenLimit != null;

  return (
    <div
      role="region"
      aria-label={localize('com_ui_memories')}
      className="flex h-full w-full flex-col overflow-hidden pt-2"
    >
      {/* Sticky header: filter, partition, usage */}
      <div className="shrink-0 space-y-2 px-3 pb-2">
        {/* Header: Filter + Create Button */}
        <div className="flex items-center gap-2">
          <FilterInput
            inputId="memory-search"
            label={localize('com_ui_memories_filter')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            containerClassName="flex-1"
          />
          {hasCreateAccess && (
            <MemoryCreateDialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
              <OGDialogTrigger asChild>
                <TooltipAnchor
                  description={localize('com_ui_create_memory')}
                  side="bottom"
                  render={
                    <Button
                      variant="outline"
                      size="icon"
                      className="size-9 shrink-0 bg-transparent"
                      aria-label={localize('com_ui_create_memory')}
                      onClick={() => setCreateDialogOpen(true)}
                    >
                      <Plus className="size-4" aria-hidden="true" />
                    </Button>
                  }
                />
              </OGDialogTrigger>
            </MemoryCreateDialog>
          )}
        </div>

        {/* Partition filter (only when agent-scoped memories exist) */}
        {partitionOptions && (
          <Dropdown
            value={activePartition}
            onChange={setPartitionFilter}
            options={partitionOptions}
            className="w-full"
            triggerClassName="w-full"
            ariaLabel={localize('com_ui_memories_partition_filter')}
            testId="memory-partition-filter"
          />
        )}

        {showUsageBadge && (
          <MemoryUsageBadge
            percentage={memData?.usagePercentage ?? 0}
            tokenLimit={tokenLimit}
            totalTokens={memData?.totalTokens ?? 0}
          />
        )}
      </div>

      {/* Only the list scrolls */}
      <PanelContent isLoading={isLoading} skeleton={<MemoryCardSkeleton />} className="px-3 pb-3">
        <MemoryList
          memories={filteredMemories}
          hasUpdateAccess={hasUpdateAccess}
          isFiltered={searchQuery.length > 0}
        />
      </PanelContent>
    </div>
  );
}
