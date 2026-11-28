import { EModelEndpoint } from 'librechat-data-provider';
import type { TAgentsMap, TEndpointsConfig } from 'librechat-data-provider';
import { favoriteEntryKey, getPinnedSelection } from './pinnedSelection';

const model = { endpoint: 'channel', model: 'model-a' };
const agent = { agentId: 'agent-a' };
const endpoints: TEndpointsConfig = {
  channel: { type: EModelEndpoint.custom, order: 0 },
  [EModelEndpoint.agents]: { order: 1 },
};
const models = { channel: ['model-a'] };
const agents: TAgentsMap = {
  'agent-a': {
    id: 'agent-a',
    name: 'Agent A',
    description: null,
    created_at: 0,
    avatar: null,
    provider: EModelEndpoint.openAI,
    model: 'model-a',
    model_parameters: {
      temperature: 1,
      maxContextTokens: 4096,
      max_context_tokens: 4096,
      max_output_tokens: 1024,
      top_p: 1,
      frequency_penalty: 0,
      presence_penalty: 0,
    },
  },
};
const options = { favorites: [model, agent], endpoints, models, agents };

describe('getPinnedSelection', () => {
  it('uses the persisted sidebar order rather than membership order', () => {
    expect(
      getPinnedSelection({
        ...options,
        order: ['convo:old', favoriteEntryKey(agent), favoriteEntryKey(model)],
      }),
    ).toEqual({ endpoint: EModelEndpoint.agents, agent_id: 'agent-a' });
  });

  it('selects the exact channel and model when it comes first', () => {
    expect(getPinnedSelection(options)).toEqual({
      endpoint: 'channel',
      endpointType: EModelEndpoint.custom,
      model: 'model-a',
    });
  });

  it('ignores removed pins and appends newly pinned items', () => {
    expect(getPinnedSelection({ ...options, order: ['convo:old', 'agent:removed'] })).toMatchObject(
      { model: 'model-a' },
    );
  });

  it('skips unavailable selections without selecting a different model on their channel', () => {
    expect(getPinnedSelection({ ...options, models: { channel: [] } })).toMatchObject({
      agent_id: 'agent-a',
    });
    expect(getPinnedSelection({ ...options, agents: {}, models: {} })).toBeUndefined();
  });

  it('keeps the existing default path when no model or agent is pinned', () => {
    expect(getPinnedSelection({ ...options, favorites: [], order: ['convo:old'] })).toBeUndefined();
  });
});
