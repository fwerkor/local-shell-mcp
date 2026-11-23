import { Bot } from 'lucide-react';
import { ProviderId } from 'librechat-data-provider';
import { createElement } from 'react';
import type { ComponentType, SVGProps } from 'react';

type ProviderArtComponent = ComponentType<SVGProps<SVGSVGElement> & { size?: number }>;

export type ProviderArt =
  | { kind: 'component'; Component: ProviderArtComponent }
  | { kind: 'asset'; src: string };

export interface ProviderIconDef {
  art: ProviderArt;
  label: string;
  /** Avatar tile background. Absent means the tile renders with no background. */
  brandColor?: string;
  /** Art inherits currentColor and follows the active theme. */
  mono?: boolean;
  className?: string;
  byModel?: (model: string) => Partial<ProviderIconDef> | undefined;
}

/**
 * Provider names identify the configured API protocol; their logos must not
 * appear in the WebUI. All models share the same neutral bot symbol.
 */
const BotArt: ProviderArtComponent = ({ size, className }) =>
  createElement(Bot, { size, className });
const genericArt: ProviderArt = { kind: 'component', Component: BotArt };
const genericIcon = (label: string): ProviderIconDef => ({
  art: genericArt,
  label,
  mono: true,
});

export const providerIcons: Record<ProviderId, ProviderIconDef> = {
  [ProviderId.openai]: genericIcon('OpenAI'),
  [ProviderId.anthropic]: genericIcon('Anthropic'),
  [ProviderId.google]: genericIcon('Google'),
  [ProviderId.azure]: genericIcon('Azure OpenAI'),
  [ProviderId.bedrock]: genericIcon('AWS Bedrock'),
  [ProviderId.xai]: genericIcon('xAI'),
  [ProviderId.moonshot]: genericIcon('Moonshot'),
  [ProviderId.anyscale]: genericIcon('Anyscale'),
  [ProviderId.apipie]: genericIcon('APIpie'),
  [ProviderId.cohere]: genericIcon('Cohere'),
  [ProviderId.deepseek]: genericIcon('DeepSeek'),
  [ProviderId.fireworks]: genericIcon('Fireworks'),
  [ProviderId.groq]: genericIcon('Groq'),
  [ProviderId.helicone]: genericIcon('Helicone'),
  [ProviderId.huggingface]: genericIcon('Hugging Face'),
  [ProviderId.lemonade]: genericIcon('AMD Lemonade'),
  [ProviderId.mistral]: genericIcon('Mistral'),
  [ProviderId.mlx]: genericIcon('MLX'),
  [ProviderId.ollama]: genericIcon('Ollama'),
  [ProviderId.openrouter]: genericIcon('OpenRouter'),
  [ProviderId.perplexity]: genericIcon('Perplexity'),
  [ProviderId.qwen]: genericIcon('Qwen'),
  [ProviderId.shuttleai]: genericIcon('ShuttleAI'),
  [ProviderId.together]: genericIcon('Together AI'),
  [ProviderId.unify]: genericIcon('Unify'),
  [ProviderId.vercel]: genericIcon('Vercel'),
};

export function getProviderIconDef(
  provider?: ProviderId | null,
  _model?: string | null,
): ProviderIconDef {
  return (provider && providerIcons[provider]) || genericIcon('AI');
}
