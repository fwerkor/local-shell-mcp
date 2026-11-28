import type { Favorite } from '~/store/favorites';

/** Length-prefix the endpoint to avoid collisions between arbitrary endpoint and model IDs. */
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

/** Existing keys first, new favorites in membership order. Ignore conversation pins. */
export function orderPinnedFavorites(
  favorites: Favorite[],
  storedOrder: string[] = [],
): Favorite[] {
  const byKey = new Map(favorites.map((favorite) => [favoriteEntryKey(favorite), favorite]));
  return [...new Set([...storedOrder, ...byKey.keys()])].flatMap((key) => {
    const favorite = byKey.get(key);
    return favorite ? [favorite] : [];
  });
}
