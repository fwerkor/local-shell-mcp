import { useMemo, useRef, useState } from 'react';
import { useDrag, useDrop } from 'react-dnd';
import { useQueryClient } from '@tanstack/react-query';
import { useMediaQuery, useToastContext } from '@librechat/client';
import { EModelEndpoint, QueryKeys } from 'librechat-data-provider';
import type { TModelSpec } from 'librechat-data-provider';
import type { ReactNode } from 'react';
import type { Endpoint } from '~/common';
import { useFavorites, useLocalize } from '~/hooks';
import { useGetPinnedOrderQuery, useUpdatePinnedOrderMutation } from '~/data-provider';
import { mergeVisibleOrder } from '~/components/Conversations/dnd';
import useFavoritesData from '~/components/Nav/Favorites/useFavoritesData';
import { favoriteEntryKey, orderPinnedFavorites } from '~/utils/pinnedFavoritesOrder';
import { CustomMenuGroup, CustomMenuSeparator } from '../CustomMenu';
import { useModelSelectorContext } from '../ModelSelectorContext';
import { EndpointModelItem } from './EndpointModelItem';
import { ModelSpecItem } from './ModelSpecItem';

const PINNED_MODEL_DRAG_TYPE = 'pinned-model-selector-row';

type Entry = { key: string } & (
  | { spec: TModelSpec }
  | { endpoint: Endpoint; model: string; agent: boolean }
);

function ReorderRow({
  entryKey,
  enabled,
  move,
  children,
}: {
  entryKey: string;
  enabled: boolean;
  move: (key: string, target: string | number) => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const hasHoverPointer = useMediaQuery('(hover: hover)');
  const [{ isDragging }, drag] = useDrag({
    type: PINNED_MODEL_DRAG_TYPE,
    item: { key: entryKey },
    canDrag: enabled && hasHoverPointer,
    collect: (monitor) => ({ isDragging: monitor.isDragging() }),
  });
  const [{ over }, drop] = useDrop<{ key: string }, void, { over: boolean }>({
    accept: PINNED_MODEL_DRAG_TYPE,
    canDrop: (item) => enabled && item.key !== entryKey,
    drop: (item) => move(item.key, entryKey),
    collect: (monitor) => ({ over: monitor.isOver() && monitor.canDrop() }),
  });
  drag(drop(ref));
  return (
    <div
      ref={ref}
      className={over ? 'rounded-lg ring-1 ring-inset ring-ring-primary' : undefined}
      style={{ opacity: isDragging ? 0.4 : 1 }}
      onKeyDownCapture={(event) => {
        if (!enabled || !event.altKey || event.ctrlKey || event.metaKey) {
          return;
        }
        if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        move(entryKey, event.key === 'ArrowUp' ? -1 : 1);
      }}
    >
      {children}
    </div>
  );
}

export default function PinnedModels() {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const queryClient = useQueryClient();
  const { mappedEndpoints, modelSpecs, selectedValues } = useModelSelectorContext();
  const { favorites, agentsMap, isLoaded, dataUpdatedAt } = useFavoritesData();
  const { removeFavoriteAgent, removeFavoriteModel } = useFavorites();
  const order = useGetPinnedOrderQuery();
  const updateOrder = useUpdatePinnedOrderMutation();
  const [announcement, setAnnouncement] = useState('');
  const enabled = order.isSuccess && !order.isFetching && isLoaded;
  const entries = useMemo<Entry[]>(() => {
    const byEndpoint = new Map(mappedEndpoints.map((endpoint) => [endpoint.value, endpoint]));
    const bySpec = new Map(modelSpecs.map((spec) => [spec.name, spec]));
    const entries: Entry[] = [];
    for (const favorite of orderPinnedFavorites(favorites, order.data)) {
      const key = favoriteEntryKey(favorite);
      if (favorite.spec) {
        const spec = bySpec.get(favorite.spec);
        if (spec) {
          entries.push({ key, spec });
        }
        continue;
      }
      if (favorite.agentId) {
        const endpoint = byEndpoint.get(EModelEndpoint.agents);
        const agent = agentsMap[favorite.agentId];
        if (endpoint && agent) {
          entries.push({
            key,
            endpoint: {
              ...endpoint,
              agentNames: { ...endpoint.agentNames, [agent.id]: agent.name ?? agent.id },
              modelIcons: { ...endpoint.modelIcons, [agent.id]: agent.avatar?.filepath },
            },
            model: agent.id,
            agent: true,
          });
        }
        continue;
      }
      const endpoint = byEndpoint.get(favorite.endpoint ?? '');
      if (endpoint && favorite.model && endpoint.models?.some((m) => m.name === favorite.model)) {
        entries.push({ key, endpoint, model: favorite.model, agent: false });
      }
    }
    return entries;
  }, [favorites, order.data, mappedEndpoints, modelSpecs, agentsMap]);

  const move = (key: string, target: string | number) => {
    if (!enabled) {
      return;
    }
    // Read the shared cache at commit time, so a chat reorder is not overwritten.
    const stored = queryClient.getQueryData<string[]>([QueryKeys.pinnedOrder]) ?? [];
    const visible = new Set(entries.map((entry) => entry.key));
    const keys = orderPinnedFavorites(favorites, stored)
      .map(favoriteEntryKey)
      .filter((key) => visible.has(key));
    const from = keys.indexOf(key);
    const to = typeof target === 'number' ? from + target : keys.indexOf(target);
    if (from < 0 || to < 0 || to >= keys.length || from === to) {
      return;
    }
    keys.splice(to, 0, ...keys.splice(from, 1));
    setAnnouncement(
      localize('com_ui_moved_to_position', { 0: String(to + 1), 1: String(keys.length) }),
    );
    const members = new Set(favorites.map(favoriteEntryKey));
    // Only prune this group's stale keys after its membership reconciles.
    const retained =
      dataUpdatedAt >= order.dataUpdatedAt
        ? stored.filter((key) => key.startsWith('convo:') || members.has(key))
        : stored;
    updateOrder.mutate(mergeVisibleOrder(retained, keys), {
      onError: () => showToast({ message: localize('com_ui_reorder_error'), status: 'error' }),
    });
  };

  if (!entries.length) {
    return null;
  }
  return (
    <>
      <CustomMenuGroup label={localize('com_ui_pinned_favorites')} data-pinned-section="favorites">
        <div className="sr-only" role="status" aria-live="polite">
          {announcement}
        </div>
        {entries.map((entry) => (
          <ReorderRow key={entry.key} entryKey={entry.key} enabled={enabled} move={move}>
            {'spec' in entry ? (
              <ModelSpecItem
                spec={entry.spec}
                isSelected={selectedValues.modelSpec === entry.spec.name}
                reorderEnabled={enabled}
              />
            ) : (
              <EndpointModelItem
                endpoint={entry.endpoint}
                modelId={entry.model}
                isFavorite
                pinned
                reorderEnabled={enabled}
                onToggleFavorite={(model) =>
                  entry.agent
                    ? removeFavoriteAgent(model)
                    : removeFavoriteModel(model, entry.endpoint.value)
                }
              />
            )}
          </ReorderRow>
        ))}
      </CustomMenuGroup>
      <CustomMenuSeparator />
    </>
  );
}
