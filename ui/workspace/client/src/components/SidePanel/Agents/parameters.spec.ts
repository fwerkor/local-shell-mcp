import type { AgentModelParameters, TEndpointsConfig } from 'librechat-data-provider';
import { resolveAgentParameterSettings, pruneAgentModelParameters } from './parameters';

describe('native agent model settings', () => {
  it.each(['openAI', 'anthropic', 'google'])(
    'only exposes supported model controls for %s',
    (provider) => {
      const settings = resolveAgentParameterSettings({ provider, model: 'test-model' });
      const keys = settings.visibleParameters.map(({ key }) => key);
      expect(keys).toContain('temperature');
      expect(keys).not.toContain('useResponsesApi');
      expect(keys).not.toContain('web_search');
      expect(keys).not.toContain('url_context');
      expect(keys).not.toContain('resendFiles');
      expect(keys).not.toContain('fileTokenLimit');
      expect(keys).not.toContain('frequency_penalty');
      expect(keys).not.toContain('disableStreaming');
    },
  );

  it('cleans retired fields even before channel metadata loads', () => {
    const settings = resolveAgentParameterSettings({
      provider: 'missing channel',
      model: 'test-model',
    });
    const previous = {
      temperature: 0,
      useResponsesApi: true,
      web_search: false,
      resendFiles: true,
    } as unknown as AgentModelParameters;
    expect(pruneAgentModelParameters(previous, settings)).toEqual({ temperature: 0 });
    expect(previous.web_search).toBe(false);
  });

  it('preserves genuine hidden model settings on unrelated saves', () => {
    const settings = resolveAgentParameterSettings({
      endpointsConfig: { Channel: { type: 'openAI', order: 1 } } as TEndpointsConfig,
      provider: 'Channel',
      model: 'test-model',
    });
    const previous = { temperature: 0, frequency_penalty: 0.2 } as AgentModelParameters;
    expect(pruneAgentModelParameters(previous, settings)).toBe(previous);
  });
});
