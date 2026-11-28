import { EModelEndpoint, getEndpointField } from 'librechat-data-provider';
import type {
  TAgentsMap,
  TEndpointsConfig,
  TModelsConfig,
  TPreset,
  TStartupConfig,
} from 'librechat-data-provider';
import type { Favorite } from '~/store/favorites';
import { getModelSpecPreset } from './endpoints';

import { orderPinnedFavorites } from './pinnedFavoritesOrder';

export function pinnedSelectionAwaitsAgents(
  favorites: Favorite[] | undefined,
  startup: TStartupConfig | undefined,
): boolean {
  return (
    favorites?.some((favorite) => {
      if (favorite.agentId) return true;
      if (!favorite.spec) return false;
      const spec = startup?.modelSpecs?.list?.find((entry) => entry.name === favorite.spec);
      return getModelSpecPreset(spec)?.endpoint === EModelEndpoint.agents;
    }) ?? false
  );
}

type PinnedSelectionOptions = {
  favorites?: Favorite[];
  order?: string[];
  endpoints?: TEndpointsConfig;
  models?: TModelsConfig;
  agents?: TAgentsMap;
  startup?: TStartupConfig;
};

/** Use the same persisted order as the model selector; new favorites not yet in that
 * order append in membership order. Conversation pins are never model picks. */
export function getPinnedSelection({
  favorites = [],
  order = [],
  endpoints,
  models,
  agents,
  startup,
}: PinnedSelectionOptions): TPreset | undefined {
  const allowedEndpoints = startup?.modelSpecs?.addedEndpoints ?? [];
  const rawEndpointVisible = (endpoint: string) =>
    startup?.interface?.modelSelect !== false &&
    !!endpoints?.[endpoint] &&
    (allowedEndpoints.length === 0 || allowedEndpoints.some((entry) => entry === endpoint));
  for (const favorite of orderPinnedFavorites(favorites, order)) {
    if (favorite.agentId) {
      if (
        rawEndpointVisible(EModelEndpoint.agents) &&
        (agents == null || agents[favorite.agentId])
      ) {
        return { endpoint: EModelEndpoint.agents, agent_id: favorite.agentId };
      }
    } else if (favorite.spec) {
      const spec = startup?.modelSpecs?.list?.find((entry) => entry.name === favorite.spec);
      const preset = getModelSpecPreset(spec);
      if (preset?.endpoint && endpoints?.[preset.endpoint]) {
        if (preset.endpoint === EModelEndpoint.agents) {
          if (preset.agent_id && (agents == null || agents[preset.agent_id])) {
            return preset;
          }
        } else {
          if (!preset.model || models == null || models[preset.endpoint]?.includes(preset.model)) {
            return preset;
          }
        }
      }
    } else if (
      favorite.endpoint &&
      favorite.model &&
      rawEndpointVisible(favorite.endpoint) &&
      (models == null || models[favorite.endpoint]?.includes(favorite.model))
    ) {
      return {
        endpoint: favorite.endpoint as EModelEndpoint,
        endpointType: getEndpointField(endpoints, favorite.endpoint, 'type'),
        model: favorite.model,
      };
    }
  }
  return undefined;
}
