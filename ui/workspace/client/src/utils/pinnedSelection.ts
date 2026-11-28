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
  for (const favorite of orderPinnedFavorites(favorites, order)) {
    if (favorite.agentId) {
      if (endpoints?.[EModelEndpoint.agents] && (agents == null || agents[favorite.agentId])) {
        return { endpoint: EModelEndpoint.agents, agent_id: favorite.agentId };
      }
    } else if (favorite.spec) {
      const spec = startup?.modelSpecs?.list?.find((entry) => entry.name === favorite.spec);
      if (spec) {
        return getModelSpecPreset(spec);
      }
    } else if (
      favorite.endpoint &&
      favorite.model &&
      endpoints?.[favorite.endpoint] &&
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
