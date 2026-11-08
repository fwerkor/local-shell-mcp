// Original LibreChat functions. See LICENSE.LibreChat and checkpoint_sources.json.
const INTERRUPT = '__interrupt__';
const LIBRECHAT_CHECKPOINT_NAMESPACE_KEY = '__librechat_checkpoint_ns';
const LIBRECHAT_CHECKPOINT_OWNER_KEY = '__librechat_checkpoint_owner';
const LIBRECHAT_LEGACY_CHECKPOINT_KEY = '__librechat_legacy_checkpoint_id';
const CHECKPOINT_NAMESPACE_SEPARATOR = '|';
function generationCheckpointNamespace(config) {
    const value = config.configurable?.[LIBRECHAT_CHECKPOINT_NAMESPACE_KEY];
    return typeof value === 'string' && value.length > 0 ? value : undefined;
}
function toStorageCheckpointConfig(config) {
    const generationNamespace = generationCheckpointNamespace(config);
    if (!generationNamespace) {
        return config;
    }
    const graphNamespace = typeof config.configurable?.checkpoint_ns === 'string' ? config.configurable.checkpoint_ns : '';
    return {
        ...config,
        configurable: {
            ...config.configurable,
            checkpoint_ns: graphNamespace === ''
                ? generationNamespace
                : `${generationNamespace}${CHECKPOINT_NAMESPACE_SEPARATOR}${graphNamespace}`,
        },
    };
}
function fromStorageCheckpointConfig(storedConfig, requestedConfig) {
    const generationNamespace = generationCheckpointNamespace(requestedConfig);
    if (!generationNamespace) {
        return storedConfig;
    }
    const graphNamespace = typeof requestedConfig.configurable?.checkpoint_ns === 'string'
        ? requestedConfig.configurable.checkpoint_ns
        : '';
    return {
        ...storedConfig,
        configurable: {
            ...storedConfig.configurable,
            ...(requestedConfig.configurable?.[LIBRECHAT_CHECKPOINT_OWNER_KEY] && {
                [LIBRECHAT_CHECKPOINT_OWNER_KEY]: requestedConfig.configurable[LIBRECHAT_CHECKPOINT_OWNER_KEY],
            }),
            ...(requestedConfig.configurable?.[LIBRECHAT_LEGACY_CHECKPOINT_KEY] && {
                [LIBRECHAT_LEGACY_CHECKPOINT_KEY]: storedConfig.configurable?.[LIBRECHAT_LEGACY_CHECKPOINT_KEY] ??
                    requestedConfig.configurable[LIBRECHAT_LEGACY_CHECKPOINT_KEY],
            }),
            thread_id: requestedConfig.configurable?.thread_id ?? storedConfig.configurable?.thread_id,
            checkpoint_ns: graphNamespace,
            [LIBRECHAT_CHECKPOINT_NAMESPACE_KEY]: generationNamespace,
        },
    };
}
function hasResumableWrite(writes) {
    return (writes ?? []).some(([channel]) => {
        const name = String(channel);
        return name === INTERRUPT || !name.startsWith('__');
    });
}
module.exports = { hasResumableWrite, generationCheckpointNamespace, toStorageCheckpointConfig, fromStorageCheckpointConfig };
