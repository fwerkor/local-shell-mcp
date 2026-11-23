import { ProviderIcon } from '@librechat/client';
import type { ProviderId } from 'librechat-data-provider';

export function ResolvedProviderIcon({
  provider,
  size = 20,
  className,
  model,
}: {
  provider?: ProviderId | null;
  imageURL?: string | null;
  size?: number;
  className?: string;
  model?: string | null;
  alt?: string;
}) {
  return <ProviderIcon provider={provider} model={model} size={size} className={className} />;
}
