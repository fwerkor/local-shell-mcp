import keyBy from 'lodash/keyBy';
import {
  agentParamSettings,
  applyModelAwareDefaults,
  getEndpointField,
  getSettingsKeys,
  normalizeEndpointName,
  resolveDropParamsUIKeys,
} from 'librechat-data-provider';
import type {
  AgentModelParameters,
  SettingDefinition,
  TEndpointsConfig,
  TStartupConfig,
} from 'librechat-data-provider';

export type AgentParameterConfig = {
  endpointsConfig?: TEndpointsConfig | null;
  startupConfig?: Pick<TStartupConfig, 'endpointsDropParamsMap'> | null;
};

export type ResolvedAgentParameterSettings = {
  /**
   * Endpoint parameters after administrator drops and removal of retired fields.
   * Preserve genuine model parameters that the current native runtime does not yet expose.
   */
  parameters: SettingDefinition[];
  /** The subset that gets a control. Model-hidden and unsupported parameters are absent. */
  visibleParameters: SettingDefinition[];
  schemaResolved: boolean;
};

/** Protocol, built-in tools and file delivery are configured outside the model. */
const RETIRED_AGENT_PARAMETER_KEYS = new Set([
  'useResponsesApi',
  'web_search',
  'url_context',
  'resendFiles',
  'imageDetail',
  'fileTokenLimit',
  'disableStreaming',
  'region',
]);

/** The native transports currently accept these sampling/context controls. */
const NATIVE_MODEL_PARAMETER_KEYS = new Set([
  'temperature',
  'top_p',
  'topP',
  'max_tokens',
  'maxTokens',
  'maxOutputTokens',
  'maxContextTokens',
  'max_context_tokens',
  'max_output_tokens',
]);

const NON_CONTROL_PARAMETER_KEYS = new Set<keyof AgentModelParameters>(['model']);

export function resolveAgentParameterSettings({
  endpointsConfig,
  model,
  provider,
  startupConfig,
}: AgentParameterConfig & {
  model: string;
  provider: string;
}): ResolvedAgentParameterSettings {
  const resolvedEndpointsConfig = endpointsConfig ?? {};
  const endpointType = getEndpointField(resolvedEndpointsConfig, provider, 'type');
  const customParams = resolvedEndpointsConfig[provider]?.customParams;
  const [combinedKey, endpointKey] = getSettingsKeys(endpointType ?? provider, model);
  const overriddenEndpointKey = customParams?.defaultParamsEndpoint ?? endpointKey;
  const dropParamsMap = startupConfig?.endpointsDropParamsMap;
  const dropParamsEntry =
    dropParamsMap?.[provider] ?? dropParamsMap?.[normalizeEndpointName(provider)];
  const resolvedDropParams = Array.isArray(dropParamsEntry)
    ? dropParamsEntry
    : dropParamsEntry?.[model];
  const dropParamsSet = resolveDropParamsUIKeys(
    Array.isArray(resolvedDropParams) ? resolvedDropParams : undefined,
    overriddenEndpointKey,
  );
  const defaultParams =
    agentParamSettings[combinedKey] ?? agentParamSettings[overriddenEndpointKey];
  const overriddenParams = customParams?.paramDefinitions;
  const overriddenParamsMap = keyBy(overriddenParams ?? [], 'key');
  /** Keep endpoint-recognized keys independent of model visibility. Only explicit administrator drops and retired settings
   * remove keys from the schema used by both save paths. */
  const endpointParams = (defaultParams ?? []).filter(
    (param) =>
      param != null &&
      !dropParamsSet.has(param.key) &&
      !RETIRED_AGENT_PARAMETER_KEYS.has(param.key),
  );
  const applyOverride = (param: SettingDefinition) =>
    (overriddenParamsMap[param.key] as SettingDefinition) ?? param;
  const parameters = endpointParams.map(applyOverride);
  const visibleParameters = applyModelAwareDefaults(
    endpointParams,
    overriddenEndpointKey,
    model,
    resolvedEndpointsConfig[provider]?.responsesApiRouting,
  )
    .map(applyOverride)
    .filter((param) => NATIVE_MODEL_PARAMETER_KEYS.has(param.key));

  return {
    schemaResolved: defaultParams != null || overriddenParams != null,
    parameters,
    visibleParameters,
  };
}

export function pruneAgentModelParameters(
  currentParameters: AgentModelParameters | undefined,
  settings: ResolvedAgentParameterSettings,
): AgentModelParameters {
  const normalizedParameters = currentParameters ?? ({} as AgentModelParameters);
  const parameterKeys = new Set(settings.parameters.map((setting) => setting.key));
  const currentKeys = Object.keys(normalizedParameters) as Array<keyof AgentModelParameters>;
  let prunedParameters: Partial<AgentModelParameters> | undefined;

  for (const key of currentKeys) {
    if (RETIRED_AGENT_PARAMETER_KEYS.has(key)) {
      prunedParameters ??= { ...normalizedParameters };
      delete prunedParameters[key];
      continue;
    }
    if (
      !settings.schemaResolved ||
      NON_CONTROL_PARAMETER_KEYS.has(key) ||
      parameterKeys.has(key) ||
      normalizedParameters[key] == null
    ) {
      continue;
    }

    prunedParameters ??= { ...normalizedParameters };
    delete prunedParameters[key];
  }

  return (prunedParameters ?? normalizedParameters) as AgentModelParameters;
}
