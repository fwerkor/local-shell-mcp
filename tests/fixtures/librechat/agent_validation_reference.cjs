// Original LibreChat source; see LICENSE.LibreChat.
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.agentUpdateSchema = exports.agentCreateSchema = exports.agentBaseSchema = exports.agentSubagentsSchema = exports.agentToolOptionsSchema = exports.toolOptionsSchema = exports.graphEdgeSchema = exports.agentSupportContactSchema = exports.agentToolResourcesSchema = exports.agentFileResourceSchema = exports.agentBaseResourceSchema = exports.agentAvatarSchema = void 0;
exports.validateAgentModel = validateAgentModel;
const zod_1 = require("zod");
const librechat_data_provider_1 = require("librechat-data-provider");
const agentCodeWorkspaceIdSchema = zod_1.z.union([
    zod_1.z.literal(''),
    zod_1.z.string().regex(librechat_data_provider_1.CODE_WORKSPACE_ID_PATTERN),
]);
/** Avatar schema shared between create and update */
exports.agentAvatarSchema = zod_1.z.object({
    filepath: zod_1.z.string(),
    source: zod_1.z.string(),
});
/** Persisted resource schema. Full file records are populated only after database authorization. */
exports.agentBaseResourceSchema = zod_1.z.object({
    file_ids: zod_1.z.array(zod_1.z.string()).optional(),
});
/** File resource schema extends base with vector_store_ids. */
exports.agentFileResourceSchema = exports.agentBaseResourceSchema.extend({
    vector_store_ids: zod_1.z.array(zod_1.z.string()).optional(),
});
/** Persisted tool resources accepted by Agent create and update APIs. */
exports.agentToolResourcesSchema = zod_1.z
    .object({
    image_edit: exports.agentBaseResourceSchema.optional(),
    execute_code: exports.agentBaseResourceSchema.optional(),
    file_search: exports.agentFileResourceSchema.optional(),
    context: exports.agentBaseResourceSchema.optional(),
    /** @deprecated Use context instead */
    ocr: exports.agentBaseResourceSchema.optional(),
})
    .optional();
/** Support contact schema for agent */
exports.agentSupportContactSchema = zod_1.z
    .object({
    name: zod_1.z.string().optional(),
    email: zod_1.z.union([zod_1.z.literal(''), zod_1.z.string().email()]).optional(),
})
    .optional();
/** Graph edge schema for agent handoffs */
exports.graphEdgeSchema = zod_1.z.object({
    from: zod_1.z.union([zod_1.z.string(), zod_1.z.array(zod_1.z.string())]),
    to: zod_1.z.union([zod_1.z.string(), zod_1.z.array(zod_1.z.string())]),
    description: zod_1.z
        .string()
        .optional()
        .transform((v) => (v === '' ? undefined : v)),
    edgeType: zod_1.z.enum(['handoff', 'direct']).optional(),
    prompt: zod_1.z
        .union([zod_1.z.string(), zod_1.z.function()])
        .optional()
        .transform((v) => (v === '' ? undefined : v)),
    excludeResults: zod_1.z.boolean().optional(),
    promptKey: zod_1.z
        .string()
        .optional()
        .transform((v) => (v === '' ? undefined : v)),
});
/** Per-tool options schema (defer_loading, allowed_callers, run_in_background, describe_intent) */
exports.toolOptionsSchema = zod_1.z.object({
    defer_loading: zod_1.z.boolean().optional(),
    allowed_callers: zod_1.z.array(zod_1.z.enum(['direct', 'code_execution'])).optional(),
    run_in_background: zod_1.z.boolean().optional(),
    describe_intent: zod_1.z.boolean().optional(),
});
/** Agent tool options - map of tool_id to tool options */
exports.agentToolOptionsSchema = zod_1.z.record(zod_1.z.string(), exports.toolOptionsSchema).optional();
/**
 * Subagent spawning configuration for an agent. `agent_ids` and `graphs` are
 * capped at the effective subagents limit (10 by default, configurable via
 * `endpoints.agents.maxSubagents`) so a crafted API request cannot trigger
 * hundreds of `processAgent` calls (DB lookup + permission check + tool
 * loading). The UI enforces the same cap, so legitimate payloads never hit
 * the bound.
 */
const graphSubagentEdgeSchema = zod_1.z
    .object({
    from: zod_1.z.union([zod_1.z.string(), zod_1.z.array(zod_1.z.string()).min(1)]),
    to: zod_1.z.union([zod_1.z.string(), zod_1.z.array(zod_1.z.string()).min(1)]),
    description: zod_1.z.string().optional(),
    edgeType: zod_1.z.literal('direct'),
    prompt: zod_1.z.string().optional(),
    excludeResults: zod_1.z.boolean().optional(),
})
    .strict();
function validateGraphSubagentTopology(graph) {
    const memberIds = new Set(graph.agent_ids);
    if (memberIds.size !== graph.agent_ids.length) {
        return `Graph subagent "${graph.type}" contains duplicate member IDs.`;
    }
    const reservedMemberIds = new Set([
        '__start__',
        '__end__',
        'messages',
        'agentMessages',
        'subagentResult',
    ]);
    const invalidMemberId = graph.agent_ids.find((agentId) => reservedMemberIds.has(agentId) || agentId.includes('|') || agentId.includes(':'));
    if (invalidMemberId) {
        return `Graph subagent "${graph.type}" member "${invalidMemberId}" is reserved by the graph runtime.`;
    }
    if (!memberIds.has(graph.entry_agent_id) || !memberIds.has(graph.result_agent_id)) {
        return `Graph subagent "${graph.type}" entry and result must reference configured members.`;
    }
    const adjacency = new Map(graph.agent_ids.map((agentId) => [agentId, new Set()]));
    const reverse = new Map(graph.agent_ids.map((agentId) => [agentId, new Set()]));
    const incomingGroups = new Map();
    const directedEdges = new Set();
    for (const edge of graph.edges) {
        const sources = Array.isArray(edge.from) ? edge.from : [edge.from];
        const destinations = Array.isArray(edge.to) ? edge.to : [edge.to];
        if (new Set(sources).size !== sources.length ||
            new Set(destinations).size !== destinations.length) {
            return `Graph subagent "${graph.type}" edge endpoints must be unique.`;
        }
        if (edge.excludeResults === true && !edge.prompt) {
            return `Graph subagent "${graph.type}" cannot exclude results without an edge prompt.`;
        }
        if (edge.prompt && destinations.length !== 1) {
            return `Graph subagent "${graph.type}" prompted edges must have one destination.`;
        }
        for (const agentId of [...sources, ...destinations]) {
            if (!memberIds.has(agentId)) {
                return `Graph subagent "${graph.type}" references unknown member "${agentId}".`;
            }
        }
        for (const destination of destinations) {
            const groups = incomingGroups.get(destination) ?? [];
            groups.push(sources);
            incomingGroups.set(destination, groups);
            for (const source of sources) {
                if (source === destination) {
                    return `Graph subagent "${graph.type}" cannot contain self-edges.`;
                }
                const edgeKey = `${source}\0${destination}`;
                if (directedEdges.has(edgeKey)) {
                    return `Graph subagent "${graph.type}" contains duplicate edges.`;
                }
                directedEdges.add(edgeKey);
                adjacency.get(source)?.add(destination);
                reverse.get(destination)?.add(source);
            }
        }
    }
    for (const [destination, groups] of incomingGroups) {
        const sources = reverse.get(destination);
        if (sources && sources.size > 1 && (groups.length !== 1 || groups[0].length !== sources.size)) {
            return `Graph subagent "${graph.type}" fan-in to "${destination}" must use one array-valued source edge.`;
        }
    }
    const roots = graph.agent_ids.filter((agentId) => reverse.get(agentId)?.size === 0);
    const sinks = graph.agent_ids.filter((agentId) => adjacency.get(agentId)?.size === 0);
    if (roots.length !== 1 || roots[0] !== graph.entry_agent_id) {
        return `Graph subagent "${graph.type}" must use entry_agent_id as its only root.`;
    }
    if (sinks.length !== 1 || sinks[0] !== graph.result_agent_id) {
        return `Graph subagent "${graph.type}" must use result_agent_id as its only sink.`;
    }
    const remainingIncoming = new Map(graph.agent_ids.map((agentId) => [agentId, reverse.get(agentId)?.size ?? 0]));
    const ready = roots.slice();
    let visitedCount = 0;
    while (ready.length > 0) {
        const source = ready.pop();
        if (source === undefined) {
            continue;
        }
        visitedCount++;
        for (const destination of adjacency.get(source) ?? []) {
            const count = (remainingIncoming.get(destination) ?? 0) - 1;
            remainingIncoming.set(destination, count);
            if (count === 0) {
                ready.push(destination);
            }
        }
    }
    if (visitedCount !== memberIds.size) {
        return `Graph subagent "${graph.type}" must be acyclic and fully connected.`;
    }
    const isSimpleChain = graph.agent_ids.every((agentId) => (adjacency.get(agentId)?.size ?? 0) <= 1 && (reverse.get(agentId)?.size ?? 0) <= 1);
    if (!isSimpleChain &&
        graph.edges.some((edge) => edge.prompt && (Array.isArray(edge.to) ? edge.to[0] : edge.to) !== graph.result_agent_id)) {
        return `Graph subagent "${graph.type}" prompts in a branched graph must target result_agent_id.`;
    }
    return undefined;
}
const graphSubagentSchema = zod_1.z
    .object({
    type: zod_1.z.string().trim().min(1),
    name: zod_1.z.string().trim().min(1),
    description: zod_1.z.string().trim().min(1),
    agent_ids: zod_1.z.array(zod_1.z.string()).min(1).max(librechat_data_provider_1.MAX_GRAPH_SUBAGENT_MEMBERS),
    edges: zod_1.z.array(graphSubagentEdgeSchema),
    entry_agent_id: zod_1.z.string(),
    result_agent_id: zod_1.z.string(),
})
    .superRefine((graph, ctx) => {
    const error = validateGraphSubagentTopology(graph);
    if (error) {
        ctx.addIssue({
            code: zod_1.z.ZodIssueCode.custom,
            message: error,
        });
    }
});
exports.agentSubagentsSchema = zod_1.z
    .object({
    enabled: zod_1.z.boolean().optional(),
    allowSelf: zod_1.z.boolean().optional(),
    shareFiles: zod_1.z.boolean().optional(),
    agent_ids: zod_1.z.array(zod_1.z.string()).optional(),
    graphs: zod_1.z.array(graphSubagentSchema).optional(),
})
    .superRefine((subagents, ctx) => {
    const maxSubagents = (0, librechat_data_provider_1.getMaxSubagents)();
    if ((subagents.agent_ids?.length ?? 0) > maxSubagents) {
        ctx.addIssue({
            code: zod_1.z.ZodIssueCode.custom,
            path: ['agent_ids'],
            message: `agent_ids must contain at most ${maxSubagents} item(s)`,
        });
    }
    if ((subagents.graphs?.length ?? 0) > maxSubagents) {
        ctx.addIssue({
            code: zod_1.z.ZodIssueCode.custom,
            path: ['graphs'],
            message: `graphs must contain at most ${maxSubagents} item(s)`,
        });
    }
    const reservedTypes = new Set(subagents.agent_ids ?? []);
    const configuredAgentIds = new Set(subagents.agent_ids ?? []);
    if (subagents.allowSelf !== false) {
        reservedTypes.add('self');
    }
    for (let graphIndex = 0; graphIndex < (subagents.graphs?.length ?? 0); graphIndex++) {
        const graph = subagents.graphs?.[graphIndex];
        if (!graph) {
            continue;
        }
        if (reservedTypes.has(graph.type)) {
            ctx.addIssue({
                code: zod_1.z.ZodIssueCode.custom,
                path: ['graphs', graphIndex, 'type'],
                message: 'Graph subagent types must be unique across all spawn targets',
            });
        }
        reservedTypes.add(graph.type);
        for (const agentId of graph.agent_ids) {
            configuredAgentIds.add(agentId);
        }
    }
    if (configuredAgentIds.size > librechat_data_provider_1.MAX_SUBAGENT_GRAPH_NODES) {
        ctx.addIssue({
            code: zod_1.z.ZodIssueCode.custom,
            message: `Subagent configuration exceeds the maximum of ${librechat_data_provider_1.MAX_SUBAGENT_GRAPH_NODES} unique agents`,
        });
    }
})
    .optional();
/** Base agent schema with all common fields */
const agentCodeEnvironmentIdSchema = zod_1.z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/);
const agentGitIdentityUpdateSchema = librechat_data_provider_1.agentGitIdentitySchema.nullable();
exports.agentBaseSchema = zod_1.z.object({
    name: zod_1.z.string().nullable().optional(),
    description: zod_1.z.string().nullable().optional(),
    instructions: zod_1.z.string().nullable().optional(),
    avatar: exports.agentAvatarSchema.nullable().optional(),
    model_parameters: zod_1.z.record(zod_1.z.unknown()).optional(),
    tools: zod_1.z.array(zod_1.z.string()).optional(),
    skills: zod_1.z.array(zod_1.z.string()).optional(),
    skills_enabled: zod_1.z.boolean().optional(),
    skill_authoring_enabled: zod_1.z.boolean().optional(),
    skills_scope: zod_1.z.nativeEnum(librechat_data_provider_1.SkillsScope).optional(),
    memory_scope: zod_1.z.nativeEnum(librechat_data_provider_1.MemoryScope).optional(),
    /** @deprecated Use edges instead */
    agent_ids: zod_1.z.array(zod_1.z.string()).optional(),
    edges: zod_1.z.array(exports.graphEdgeSchema).optional(),
    end_after_tools: zod_1.z.boolean().optional(),
    hide_sequential_outputs: zod_1.z.boolean().optional(),
    stateful_code_sessions: zod_1.z.boolean().optional(),
    stateful_code_environment: zod_1.z.enum(['user', 'agent-user', 'conversation']).optional(),
    code_environment_id: agentCodeEnvironmentIdSchema.optional(),
    code_workspace_id: agentCodeWorkspaceIdSchema.optional(),
    repositoryInstructions: zod_1.z.enum(['prefer', 'defer', 'off']).optional(),
    git_identity: librechat_data_provider_1.agentGitIdentitySchema,
    artifacts: zod_1.z.string().optional(),
    recursion_limit: zod_1.z.number().optional(),
    conversation_starters: zod_1.z.array(zod_1.z.string()).optional(),
    tool_resources: exports.agentToolResourcesSchema,
    tool_options: exports.agentToolOptionsSchema,
    subagents: exports.agentSubagentsSchema,
    support_contact: exports.agentSupportContactSchema,
    category: zod_1.z.string().optional(),
});
/** Create schema extends base with required fields for creation */
exports.agentCreateSchema = exports.agentBaseSchema.extend({
    provider: zod_1.z.string(),
    model: zod_1.z.string().nullable(),
    tools: zod_1.z.array(zod_1.z.string()).optional().default([]),
});
/** Update schema extends base with all fields optional and additional update-only fields */
exports.agentUpdateSchema = exports.agentBaseSchema.extend({
    avatar: zod_1.z.union([exports.agentAvatarSchema, zod_1.z.null()]).optional(),
    code_environment_id: agentCodeEnvironmentIdSchema.nullable().optional(),
    code_workspace_id: agentCodeWorkspaceIdSchema.optional(),
    repositoryInstructions: zod_1.z.enum(['prefer', 'defer', 'off']).optional(),
    git_identity: agentGitIdentityUpdateSchema,
    provider: zod_1.z.string().optional(),
    model: zod_1.z.string().nullable().optional(),
});
/**
 * Validates an agent's model against the available models configuration.
 * This is a non-middleware version of validateModel that can be used
 * in service initialization flows.
 *
 * @param params - Validation parameters
 * @returns Object indicating whether the model is valid and any error details
 */
async function validateAgentModel(params) {
    const { req, res, agent, modelsConfig, logViolation } = params;
    const { model, provider: endpoint } = agent;
    if (!model) {
        return {
            isValid: false,
            error: {
                message: `{ "type": "${librechat_data_provider_1.ErrorTypes.MISSING_MODEL}", "info": "${endpoint}" }`,
            },
        };
    }
    if (!modelsConfig) {
        return {
            isValid: false,
            error: {
                message: `{ "type": "${librechat_data_provider_1.ErrorTypes.MODELS_NOT_LOADED}" }`,
            },
        };
    }
    const availableModels = modelsConfig[(0, librechat_data_provider_1.resolveModelCatalogKey)(endpoint, modelsConfig)];
    if (!availableModels) {
        return {
            isValid: false,
            error: {
                message: `{ "type": "${librechat_data_provider_1.ErrorTypes.ENDPOINT_MODELS_NOT_LOADED}", "info": "${endpoint}" }`,
            },
        };
    }
    const validModel = !!availableModels.find((availableModel) => availableModel === model);
    if (validModel) {
        return { isValid: true };
    }
    const { ILLEGAL_MODEL_REQ_SCORE: score = 1 } = process.env ?? {};
    const type = librechat_data_provider_1.ViolationTypes.ILLEGAL_MODEL_REQUEST;
    const errorMessage = {
        type,
        model,
        endpoint,
    };
    await logViolation(req, res, type, errorMessage, score);
    return {
        isValid: false,
        error: {
            message: `{ "type": "${librechat_data_provider_1.ViolationTypes.ILLEGAL_MODEL_REQUEST}", "info": "${endpoint}|${model}" }`,
        },
    };
}
