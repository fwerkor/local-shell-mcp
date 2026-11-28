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

/** A key identifies a row everywhere in this section, so the encoding has to be
 *  injective. The favorites API accepts any string for an endpoint or a model,
 *  so a plain `endpoint::model` join collides: `a::b` + `c` and `a` + `b::c`
 *  both read back as `a::b::c`, and the dedupe below would then hide one of two
 *  distinct favorites. Length-prefixing the endpoint makes the split exact. */
export const favoriteEntryKey = (favorite: Favorite): string => {
  if (favorite.agentId) {
    return `agent:${favorite.agentId}`;
  }
  if (favorite.spec) {
    return `spec:${favorite.spec}`;
  }
  const endpoint = favorite.endpoint ?? '';
  return `model:${endpoint.length}:${endpoint}:${favorite.model ?? ''}`;
};

type PinnedSelectionOptions = {
  favorites?: Favorite[];
  order?: string[];
  endpoints?: TEndpointsConfig;
  models?: TModelsConfig;
  agents?: TAgentsMap;
  startup?: TStartupConfig;
};

/** Use the same persisted order as the sidebar; new favorites not yet in that
 * order append in membership order. Conversation pins are never model picks. */
export function getPinnedSelection({
  favorites = [],
  order = [],
  endpoints,
  models,
  agents,
  startup,
}: PinnedSelectionOptions): TPreset | undefined {
  const byKey = new Map(favorites.map((favorite) => [favoriteEntryKey(favorite), favorite]));
  const keys = new Set([...order, ...byKey.keys()]);
  for (const key of keys) {
    const favorite = byKey.get(key);
    if (!favorite) {
      continue;
    }
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
