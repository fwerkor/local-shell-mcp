import { useMemo } from 'react';
import { getEndpointField, resolveProviderId, endpointToProvider } from 'librechat-data-provider';
import type { TEndpointsConfig, EModelEndpoint, ProviderId } from 'librechat-data-provider';
import { isImageURL } from '~/utils/icons';

export interface ProviderIconResolution {
  provider: ProviderId | null;
  imageURL: string | null;
}

export interface ProviderIconParams {
  endpoint?: string | null;
  endpointsConfig?: TEndpointsConfig | null;
  iconURL?: string | null;
}

/**
 * Prefer the neutral provider icon even when a channel, model spec, or
 * conversation carries a legacy provider-logo URL. Only non-provider custom
 * images (such as custom agent avatars) may be resolved as image URLs.
 */
export function resolveProviderIcon({
  endpoint,
  endpointsConfig,
  iconURL,
}: ProviderIconParams): ProviderIconResolution {
  const configured = getEndpointField(endpointsConfig, endpoint, 'iconURL');
  const candidate = iconURL || configured;
  const provider =
    resolveProviderId(candidate) ||
    getEndpointField(endpointsConfig, endpoint, 'providerId') ||
    (endpoint ? endpointToProvider[endpoint as EModelEndpoint] : undefined) ||
    resolveProviderId(endpoint);

  if (provider) {
    return { provider, imageURL: null };
  }

  return { provider: null, imageURL: isImageURL(candidate) ? candidate : null };
}

/** Memoized form of {@link resolveProviderIcon}, for use outside render callbacks. */
export function useProviderIcon({
  endpoint,
  endpointsConfig,
  iconURL,
}: ProviderIconParams): ProviderIconResolution {
  return useMemo(
    () => resolveProviderIcon({ endpoint, endpointsConfig, iconURL }),
    [endpoint, endpointsConfig, iconURL],
  );
}
