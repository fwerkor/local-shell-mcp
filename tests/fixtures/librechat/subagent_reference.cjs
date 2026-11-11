// Original MIT-licensed LibreChat/agents functions; see LICENSE files and subagent_source_hashes.json.
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SubagentToolDefinition = exports.SubagentToolSchema = exports.SubagentToolDescription = exports.SubagentToolName = exports.INTENT_PROPERTY = exports.INTENT_DESCRIPTION = exports.INTENT_LABEL_MARKER = void 0;
exports.buildSubagentToolParams = buildSubagentToolParams;
exports.createSubagentToolDefinition = createSubagentToolDefinition;
exports.filterSubagentResult = filterSubagentResult;
exports.resolveRecursionLimit = resolveRecursionLimit;
exports.resolveSubagentMaxTurns = resolveSubagentMaxTurns;
const Constants = { SUBAGENT: 'subagent' };
const ContentTypes = { TEXT: 'text' };
const TEXT_DELTA_CONTENT_TYPE = 'text_delta';
exports.INTENT_LABEL_MARKER = 'ALWAYS write this field FIRST';
exports.INTENT_DESCRIPTION = `${exports.INTENT_LABEL_MARKER}, before any other argument. One present-progressive ` +
    'sentence saying what THIS call is about to do: "Searching for OAuth handling ' +
    'in the callback router". Shown to the user as this call\'s live status. ' +
    'Never name the tool. Sibling calls to one tool must differ.';
exports.INTENT_PROPERTY = Object.freeze({
    type: 'string',
    description: exports.INTENT_DESCRIPTION,
});
exports.SubagentToolName = Constants.SUBAGENT;
exports.SubagentToolDescription = `Delegate a task to a specialized subagent or bounded agent team that runs in an isolated context window. The delegated execution returns only its designated final text result — all intermediate tool calls, reasoning, and context stay isolated.

WHEN TO USE:
- The task is self-contained and can be described in a single prompt.
- You want to offload verbose or exploratory work without bloating your own context.
- A specialized subagent is available for the task domain.

WHAT HAPPENS:
- A fresh agent or configured agent graph is created with the task description as its only input, unless the host enables child-thread continuation and you provide a saved thread id.
- The delegated agent or team runs to completion using isolated tools and context.
- Only the single agent's final response or the graph's designated result-agent response is returned to you.

CONSTRAINTS:
- subagent_type must match one of the available types listed below.
- The subagent cannot see your conversation history.`;
const DESCRIPTION_PROP_DESCRIPTION = 'Complete task description for the subagent. This is the ONLY information it receives — include all necessary context, requirements, and constraints.';
const SUBAGENT_TYPE_PROP_DESCRIPTION = 'Which subagent type to delegate to. Must be one of the available types.';
const RUN_IN_BACKGROUND_PROP_DESCRIPTION = 'Set true to start the subagent as a detached process-local task and return a background_task_id immediately. Poll the host background-task tool to collect its result. The task can outlive this turn but does not survive a process restart.';
const SUBAGENT_THREAD_PROP_DESCRIPTION = 'Continue a host-owned child thread using a fresh execution lease. The saved thread must belong to this scope and subagent type. Only available with run_in_background.';
exports.SubagentToolSchema = {
    type: 'object',
    properties: {
        intent: { ...exports.INTENT_PROPERTY },
        description: {
            type: 'string',
            description: DESCRIPTION_PROP_DESCRIPTION,
        },
        subagent_type: {
            type: 'string',
            description: SUBAGENT_TYPE_PROP_DESCRIPTION,
        },
    },
    required: ['description', 'subagent_type'],
};
exports.SubagentToolDefinition = {
    name: exports.SubagentToolName,
    description: exports.SubagentToolDescription,
    parameters: exports.SubagentToolSchema,
};
function buildSubagentToolParams(configs, options = {}) {
    const types = configs.map((c) => c.type);
    const typeDescriptions = configs
        .map((c) => `- "${c.type}" (${c.name}): ${c.description}`)
        .join('\n');
    return {
        name: exports.SubagentToolName,
        schema: {
            type: 'object',
            properties: {
                intent: { ...exports.INTENT_PROPERTY },
                description: {
                    type: 'string',
                    description: DESCRIPTION_PROP_DESCRIPTION,
                },
                subagent_type: {
                    type: 'string',
                    enum: types,
                    description: `${SUBAGENT_TYPE_PROP_DESCRIPTION} Available: ${types.join(', ')}.`,
                },
                ...(options.background === true
                    ? {
                        run_in_background: {
                            type: 'boolean',
                            description: RUN_IN_BACKGROUND_PROP_DESCRIPTION,
                        },
                    }
                    : {}),
                ...(options.background === true &&
                    options.threadContinuation === true
                    ? {
                        subagent_thread_id: {
                            type: 'string',
                            description: SUBAGENT_THREAD_PROP_DESCRIPTION,
                        },
                    }
                    : {}),
            },
            required: ['description', 'subagent_type'],
        },
        description: `${exports.SubagentToolDescription}${options.background === true
            ? '\n\nBACKGROUND EXECUTION:\n- Set run_in_background to true when you do not need the result immediately. The call returns a background_task_id; use the host background-task tools to poll, steer, queue, interrupt, or cancel it.'
            : ''}${options.background === true && options.threadContinuation === true
            ? '\n- To continue a completed child later, set run_in_background and pass its subagent_thread_id. The host starts a fresh execution from saved history; it does not restore a completed runtime.'
            : ''}\n\nAvailable types:\n${typeDescriptions}`,
    };
}
function createSubagentToolDefinition(configs) {
    const params = buildSubagentToolParams(configs);
    return {
        name: params.name,
        description: params.description,
        parameters: params.schema,
    };
}
function filterSubagentResult(messages) {
    for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i]._getType() !== 'ai') {
            continue;
        }
        const content = messages[i].content;
        if (typeof content === 'string') {
            if (content)
                return content;
            continue;
        }
        if (!Array.isArray(content)) {
            continue;
        }
        const textParts = [];
        let textDeltaParts = [];
        let textDeltaIndex;
        const flushTextDeltaParts = () => {
            if (textDeltaParts.length === 0) {
                return;
            }
            textParts.push(textDeltaParts.join(''));
            textDeltaParts = [];
            textDeltaIndex = undefined;
        };
        for (const block of content) {
            if (typeof block === 'string') {
                flushTextDeltaParts();
                if (block !== '') {
                    textParts.push(block);
                }
                continue;
            }
            const type = 'type' in block && typeof block.type === 'string' ? block.type : '';
            const isTextDelta = type === TEXT_DELTA_CONTENT_TYPE;
            const isText = type === ContentTypes.TEXT || isTextDelta;
            const text = isText && 'text' in block && typeof block.text === 'string'
                ? block.text
                : '';
            if (isTextDelta) {
                if (text === '') {
                    continue;
                }
                const index = 'index' in block &&
                    (typeof block.index === 'string' || typeof block.index === 'number')
                    ? block.index
                    : undefined;
                if (textDeltaIndex != null &&
                    index != null &&
                    index !== textDeltaIndex) {
                    flushTextDeltaParts();
                }
                textDeltaIndex ??= index;
                textDeltaParts.push(text);
                continue;
            }
            if (type === ContentTypes.TEXT && text === '') {
                continue;
            }
            flushTextDeltaParts();
            if (text !== '') {
                textParts.push(text);
            }
        }
        flushTextDeltaParts();
        if (textParts.length > 0) {
            return textParts.join('\n');
        }
    }
    return 'Task completed';
}
const DEFAULT_RECURSION_LIMIT = 50;
const SUBAGENT_RECURSION_MULTIPLIER = 3;
function resolveRecursionLimit(agentsEConfig, agent) {
    let limit = agentsEConfig?.recursionLimit ?? DEFAULT_RECURSION_LIMIT;
    if (typeof agent?.recursion_limit === 'number' && agent.recursion_limit > 0) {
        limit = agent.recursion_limit;
    }
    if (typeof agentsEConfig?.maxRecursionLimit === 'number' &&
        agentsEConfig.maxRecursionLimit > 0 &&
        limit > agentsEConfig.maxRecursionLimit) {
        limit = agentsEConfig.maxRecursionLimit;
    }
    return limit;
}
function resolveSubagentMaxTurns(agentsEConfig, agent) {
    const limit = resolveRecursionLimit(agentsEConfig, agent);
    return Math.floor(limit / SUBAGENT_RECURSION_MULTIPLIER);
}
