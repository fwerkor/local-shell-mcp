import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { EModelEndpoint, ProviderId } from 'librechat-data-provider';
import type { TEndpointsConfig } from 'librechat-data-provider';
import {
  getProviderIconDef,
  providerIcons,
} from '../../../../packages/client/src/icons/provider/registry';
import { ProviderIcon } from '../../../../packages/client/src/icons/provider/Icon';
import { resolveProviderIcon } from './useProviderIcon';

describe('provider-neutral model icon rendering', () => {
  it('uses the same bot symbol for every supported provider and model', () => {
    for (const provider of Object.values(ProviderId)) {
      const def = getProviderIconDef(provider, 'gpt-5.1');
      expect(def.art.kind).toBe('component');
      expect(def.art).toBe(getProviderIconDef(null).art);
      expect(def.mono).toBe(true);
      expect(def.brandColor).toBeUndefined();
      expect(def.label).toBe(providerIcons[provider].label);
    }
    expect(getProviderIconDef(null).art.kind).toBe('component');
  });

  it('actually renders a neutral bot SVG, not a vendor image', () => {
    for (const provider of [ProviderId.openai, ProviderId.anthropic, ProviderId.deepseek]) {
      const html = renderToStaticMarkup(createElement(ProviderIcon, { provider, size: 20 }));
      expect(html).toContain('lucide-bot');
      expect(html).not.toContain('<img');
    }
  });

  it('does not render old provider logo URLs from endpoint settings', () => {
    const endpointsConfig = {
      [EModelEndpoint.openAI]: {
        providerId: ProviderId.openai,
        iconURL: 'https://example.com/openai-logo.svg',
      },
    } as unknown as TEndpointsConfig;

    expect(resolveProviderIcon({ endpoint: EModelEndpoint.openAI, endpointsConfig })).toEqual({
      provider: ProviderId.openai,
      imageURL: null,
    });
    expect(
      resolveProviderIcon({
        endpoint: EModelEndpoint.openAI,
        endpointsConfig,
        iconURL: 'https://example.com/another-brand-logo.png',
      }),
    ).toEqual({ provider: ProviderId.openai, imageURL: null });
  });

  it('keeps image URLs for custom non-provider entities', () => {
    expect(
      resolveProviderIcon({
        endpoint: EModelEndpoint.agents,
        iconURL: 'https://example.com/custom-agent.png',
      }),
    ).toEqual({ provider: null, imageURL: 'https://example.com/custom-agent.png' });
  });

  it('keeps the provider label available even though model art is neutral', () => {
    expect(getProviderIconDef(ProviderId.anthropic, 'claude-4').label).toBe('Anthropic');
    expect(getProviderIconDef(ProviderId.google, 'gemini-3').label).toBe('Google');
  });
});
