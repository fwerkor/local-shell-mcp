import { favoriteEntryKey, orderPinnedFavorites } from './pinnedFavoritesOrder';

describe('model selector pinned order', () => {
  const first = { endpoint: 'Codex', model: 'gpt' };
  const second = { endpoint: 'DeepSeek', model: 'flash' };
  const agent = { agentId: 'agent_1' };
  const spec = { spec: 'configured' };

  it('uses saved order across models, agents and specs without including chats', () => {
    expect(
      orderPinnedFavorites(
        [first, second, agent, spec],
        [
          'convo:one',
          favoriteEntryKey(agent),
          favoriteEntryKey(second),
          'convo:two',
          favoriteEntryKey(first),
        ],
      ),
    ).toEqual([agent, second, first, spec]);
  });

  it('deduplicates membership and saved keys, ignores stale pins, and appends new pins', () => {
    expect(
      orderPinnedFavorites(
        [first, first, agent, second],
        ['agent:removed', favoriteEntryKey(second), favoriteEntryKey(second)],
      ),
    ).toEqual([second, first, agent]);
  });

  it('keeps identically named models from distinct channels separate', () => {
    const other = { ...first, endpoint: 'Other' };
    expect(orderPinnedFavorites([first, other], [favoriteEntryKey(other)])).toEqual([other, first]);
    expect(favoriteEntryKey({ endpoint: 'a:b', model: 'c' })).not.toBe(
      favoriteEntryKey({ endpoint: 'a', model: 'b:c' }),
    );
  });
});
