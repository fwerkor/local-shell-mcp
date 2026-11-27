import { useMemo } from 'react';
import { isAgentsEndpoint, resolveModelCatalogKey } from 'librechat-data-provider';
import type { TConversation, TModelTokenomics } from 'librechat-data-provider';
import {
  useGetStartupConfig,
  useTokenConfigQuery,
  useGetAgentByIdQuery,
  useGetEndpointsQuery,
} from '~/data-provider';
import { getModelSpec } from '~/utils';

export interface TokenLimits {
  /** Statically resolved max context; live snapshots override this at run time */
  maxContextTokens?: number;
  rates?: TModelTokenomics;
  endpoint?: string;
  channel?: string;
  model?: string;
}

function toNumber(value: unknown): number | undefined {
  const num = typeof value === 'string' ? parseFloat(value) : value;
  return typeof num === 'number' && Number.isFinite(num) && num > 0 ? num : undefined;
}

/**
 * Mirrors the backend resolution chain (packages/api agents/initialize.ts):
 * explicit conversation setting → agent params → model spec preset →
 * server-resolved token config lookup.
 */
export default function useTokenLimits(conversation: TConversation | null): TokenLimits {
  const { data: startupConfig } = useGetStartupConfig();
  const { data: tokenConfig } = useTokenConfigQuery();
  const { data: endpointsConfig } = useGetEndpointsQuery();

  const endpoint = conversation?.endpoint ?? '';
  const agentId = isAgentsEndpoint(endpoint) ? conversation?.agent_id : null;
  const { data: agent } = useGetAgentByIdQuery(agentId);

  const spec = conversation?.spec;
  const model = conversation?.model;
  const maxContextSetting = conversation?.maxContextTokens;

  return useMemo(() => {
    const specPreset = getModelSpec({ specName: spec, startupConfig })?.preset;

    let lookupEndpoint = endpoint;
    let lookupModel = model ?? '';
    if (agent) {
      lookupEndpoint = agent.provider ?? endpoint;
      lookupModel = agent.model ?? lookupModel;
    } else if (specPreset) {
      lookupEndpoint = specPreset.endpoint ?? lookupEndpoint;
      lookupModel = lookupModel || (specPreset.model ?? '');
    }
    const channel = agentId && !agent ? undefined : lookupEndpoint;
    lookupEndpoint = resolveModelCatalogKey(lookupEndpoint, tokenConfig);

    const rates = tokenConfig?.[lookupEndpoint]?.[lookupModel];
    const maxContextTokens =
      toNumber(maxContextSetting) ??
      toNumber(agent?.model_parameters?.max_context_tokens) ??
      toNumber(agent?.model_parameters?.maxContextTokens) ??
      toNumber(specPreset?.maxContextTokens) ??
      toNumber(endpointsConfig?.agents?.maxContextTokens) ??
      rates?.context;

    return { maxContextTokens, rates, endpoint: lookupEndpoint, channel, model: lookupModel };
  }, [
    endpoint,
    model,
    spec,
    maxContextSetting,
    agent,
    agentId,
    startupConfig,
    tokenConfig,
    endpointsConfig,
  ]);
}
