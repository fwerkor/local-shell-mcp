// Original LibreChat/agents functions; licenses beside this fixture.
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.buildToolApprovalPayload = buildToolApprovalPayload;
exports.createToolPolicyHook = createToolPolicyHook;
exports.sliceWithoutSplittingSurrogates = sliceWithoutSplittingSurrogates;
exports.truncateToolResultContent = truncateToolResultContent;
const DEFAULT_REVIEW_DECISIONS = ['approve', 'reject', 'edit'];
function buildToolApprovalPayload(toolCalls, decisionsByToolName) {
    return {
        type: 'tool_approval',
        action_requests: toolCalls.map((tc) => ({
            name: tc.name,
            arguments: tc.arguments,
            tool_call_id: tc.tool_call_id,
            description: tc.description,
        })),
        review_configs: toolCalls.map((tc) => ({
            action_name: tc.name,
            tool_call_id: tc.tool_call_id,
            allowed_decisions: decisionsByToolName?.[tc.name] ?? DEFAULT_REVIEW_DECISIONS,
        })),
    };
}
function globToRegex(pattern) {
    const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp('^' + escaped.replace(/\*/g, '.*') + '$');
}
function compileMatchers(patterns) {
    if (patterns == null || patterns.length === 0) {
        return () => false;
    }
    const regexes = patterns.map(globToRegex);
    return (toolName) => {
        for (const regex of regexes) {
            if (regex.test(toolName)) {
                return true;
            }
        }
        return false;
    };
}
function formatReason(template, toolName) {
    if (template == null) {
        return undefined;
    }
    return template.replace(/\{tool\}/g, toolName);
}
function createToolPolicyHook(config) {
    const denyMatcher = compileMatchers(config.deny);
    const allowMatcher = compileMatchers(config.allow);
    const askMatcher = compileMatchers(config.ask);
    const mode = config.mode ?? 'default';
    const reasonTemplate = config.reason;
    return async (input) => {
        const toolName = input.toolName;
        const decision = decide(toolName, mode, denyMatcher, allowMatcher, askMatcher);
        if (decision === 'allow') {
            return { decision };
        }
        const reason = formatReason(reasonTemplate, toolName);
        if (reason != null) {
            return { decision, reason };
        }
        return { decision };
    };
}
function decide(toolName, mode, denyMatch, allowMatch, askMatch) {
    if (denyMatch(toolName)) {
        return 'deny';
    }
    if (askMatch(toolName)) {
        return 'ask';
    }
    if (allowMatch(toolName)) {
        return 'allow';
    }
    if (mode === 'bypass') {
        return 'allow';
    }
    if (mode === 'dontAsk') {
        return 'deny';
    }
    return 'ask';
}
function sliceWithoutSplittingSurrogates(value, start, end) {
    const sliced = value.slice(start, end);
    const first = sliced.charCodeAt(0);
    const last = sliced.charCodeAt(sliced.length - 1);
    const trimStart = first >= 0xdc00 && first <= 0xdfff;
    const trimEnd = last >= 0xd800 && last <= 0xdbff;
    return trimStart || trimEnd
        ? sliced.slice(trimStart ? 1 : 0, sliced.length - (trimEnd ? 1 : 0))
        : sliced;
}
function truncateToolResultContent(content, maxChars) {
    if (content.length <= maxChars) {
        return content;
    }
    const indicator = `\n\n… [truncated: ${content.length} chars exceeded ${maxChars} limit] …\n\n`;
    const available = maxChars - indicator.length;
    if (available <= 0) {
        return sliceWithoutSplittingSurrogates(content, 0, maxChars);
    }
    // When budget is too small for a meaningful tail, fall back to head-only
    if (available < 200) {
        return (sliceWithoutSplittingSurrogates(content, 0, available) +
            indicator.trimEnd());
    }
    const headSize = Math.ceil(available * 0.7);
    const tailSize = available - headSize;
    // Try to break at newline boundaries for cleaner output
    let headEnd = headSize;
    const headNewline = content.lastIndexOf('\n', headSize);
    if (headNewline > headSize - 200 && headNewline > 0) {
        headEnd = headNewline;
    }
    let tailStart = content.length - tailSize;
    const tailNewline = content.indexOf('\n', tailStart);
    if (tailNewline > 0 && tailNewline < tailStart + 200) {
        tailStart = tailNewline + 1;
    }
    return (sliceWithoutSplittingSurrogates(content, 0, headEnd) +
        indicator +
        sliceWithoutSplittingSurrogates(content, tailStart));
}
function buildToolApprovalInterruptPayload(askEntries, hookSessionId) {
    return {
        type: 'tool_approval',
        ...(hookSessionId == null || hookSessionId === ''
            ? {}
            : { hook_session_id: hookSessionId }),
        action_requests: askEntries.map(({ entry, reason }) => {
            const request = {
                tool_call_id: entry.call.id,
                name: entry.call.name,
                arguments: entry.args,
            };
            if (reason != null) {
                request.description = reason;
            }
            return request;
        }),
        review_configs: askEntries.map(({ entry, allowedDecisions }) => ({
            action_name: entry.call.name,
            tool_call_id: entry.call.id,
            allowed_decisions: (allowedDecisions ?? [
                'approve',
                'reject',
                'edit',
                'respond',
            ]),
        })),
    };
}
function normalizeApprovalDecisions(callIds, resumeValue) {
    const map = new Map();
    if (resumeValue == null) {
        return map;
    }
    if (Array.isArray(resumeValue)) {
        const limit = Math.min(callIds.length, resumeValue.length);
        for (let i = 0; i < limit; i++) {
            map.set(callIds[i], resumeValue[i]);
        }
        return map;
    }
    if (typeof resumeValue === 'object') {
        for (const callId of callIds) {
            const decision = resumeValue[callId];
            if (decision !== undefined) {
                map.set(callId, decision);
            }
        }
    }
    return map;
}

Object.assign(exports, {buildToolApprovalInterruptPayload, normalizeApprovalDecisions});
