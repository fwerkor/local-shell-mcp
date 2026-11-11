// Original LibreChat functions; see LICENSE.LibreChat and source_hashes.json.
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.isToolApprovalPayloadValid = isToolApprovalPayloadValid;
exports.mapToolApprovalResolutions = mapToolApprovalResolutions;
exports.mapAskUserAnswer = mapAskUserAnswer;
exports.mapAskUserAnswers = mapAskUserAnswers;
exports.resolveAskUserQuestionResume = resolveAskUserQuestionResume;
exports.findUndecidedToolCalls = findUndecidedToolCalls;
exports.hasInvalidToolApprovalResolutions = hasInvalidToolApprovalResolutions;
exports.findDisallowedDecisions = findDisallowedDecisions;
exports.findIncompleteDecisions = findIncompleteDecisions;
exports.resolveToolApprovalResume = resolveToolApprovalResume;
function isToolApprovalPayloadValid(payload) {
    if (payload.action_requests.length !== payload.review_configs.length) {
        return false;
    }
    const requestedIds = new Set();
    for (const request of payload.action_requests) {
        if (typeof request.tool_call_id !== 'string' ||
            request.tool_call_id.length === 0 ||
            requestedIds.has(request.tool_call_id)) {
            return false;
        }
        requestedIds.add(request.tool_call_id);
    }
    const reviewedIds = new Set();
    for (const config of payload.review_configs) {
        if (typeof config.tool_call_id !== 'string' ||
            config.tool_call_id.length === 0 ||
            reviewedIds.has(config.tool_call_id)) {
            return false;
        }
        if (!requestedIds.has(config.tool_call_id)) {
            return false;
        }
        reviewedIds.add(config.tool_call_id);
    }
    return true;
}
function mapToolApprovalResolutions(resolutions) {
    const decisions = {};
    for (const resolution of resolutions) {
        decisions[resolution.tool_call_id] = toSdkDecision(resolution);
    }
    return decisions;
}
function toSdkDecision(resolution) {
    switch (resolution.decision) {
        case 'approve':
            return { type: 'approve' };
        case 'reject':
            return { type: 'reject', reason: resolution.reason };
        case 'edit':
            // `editedArguments` is required for edit on the wire; default to {} so a
            // malformed payload re-runs the tool with empty args rather than throwing.
            return { type: 'edit', updatedInput: resolution.editedArguments ?? {} };
        case 'respond':
            return { type: 'respond', responseText: resolution.responseText ?? '' };
        default:
            // Unknown decision (forward-compat / malformed): fail closed by rejecting,
            // never by silently approving a tool the user didn't sanction.
            return { type: 'reject', reason: 'Unrecognized approval decision' };
    }
}
function mapAskUserAnswer(resolution) {
    return { answer: resolution.answer };
}
function mapAskUserAnswers(resolution) {
    return { answers: resolution.answers };
}
const MAX_ASK_ANSWER_LENGTH = 16_000;
const ASK_QUESTION_ID_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
const MAX_ASK_QUESTIONS = 4;
function resolveAskUserQuestionResume(payload, body) {
    if (!Array.isArray(payload.questions)) {
        if (typeof body.answer !== 'string' || body.answer.length === 0) {
            return { status: 400, error: 'An answer is required' };
        }
        if (body.answer.length > MAX_ASK_ANSWER_LENGTH) {
            return { status: 400, error: 'Answer exceeds the maximum length' };
        }
        return { resumeValue: mapAskUserAnswer({ answer: body.answer }) };
    }
    if (payload.questions.length === 0 || payload.questions.length > MAX_ASK_QUESTIONS) {
        return { status: 400, error: 'The pending question batch is invalid' };
    }
    if (body.answers == null || typeof body.answers !== 'object' || Array.isArray(body.answers)) {
        return { status: 400, error: 'Answers are required for every question' };
    }
    const submittedAnswers = body.answers;
    const answers = Object.create(null);
    const expectedIds = new Set();
    for (const question of payload.questions) {
        const { id } = question;
        if (typeof id !== 'string' || !ASK_QUESTION_ID_PATTERN.test(id) || expectedIds.has(id)) {
            return { status: 400, error: 'The pending question batch is invalid' };
        }
        expectedIds.add(id);
        const answer = Object.getOwnPropertyDescriptor(submittedAnswers, id)?.value;
        if (typeof answer !== 'string' || answer.length === 0) {
            return { status: 400, error: 'Answers are required for every question' };
        }
        if (answer.length > MAX_ASK_ANSWER_LENGTH) {
            return { status: 400, error: 'An answer exceeds the maximum length' };
        }
        answers[id] = answer;
    }
    if (Object.keys(submittedAnswers).some((id) => !expectedIds.has(id))) {
        return { status: 400, error: 'Answers contain an unknown question id' };
    }
    return { resumeValue: mapAskUserAnswers({ answers }) };
}
function findUndecidedToolCalls(payload, resolutions) {
    const decided = new Set(resolutions.map((r) => r.tool_call_id));
    return payload.action_requests.map((a) => a.tool_call_id).filter((id) => !decided.has(id));
}
function hasInvalidToolApprovalResolutions(payload, resolutions) {
    const requestedIds = new Set(payload.action_requests.map((request) => request.tool_call_id));
    const resolutionIds = new Set();
    for (const resolution of resolutions) {
        if (resolutionIds.has(resolution.tool_call_id) || !requestedIds.has(resolution.tool_call_id)) {
            return true;
        }
        resolutionIds.add(resolution.tool_call_id);
    }
    return false;
}
function findDisallowedDecisions(payload, resolutions) {
    const allowedByToolCallId = new Map();
    for (const config of payload.review_configs) {
        allowedByToolCallId.set(config.tool_call_id, new Set(config.allowed_decisions));
    }
    return resolutions
        .filter((r) => !allowedByToolCallId.get(r.tool_call_id)?.has(r.decision))
        .map((r) => r.tool_call_id);
}
function findIncompleteDecisions(resolutions) {
    return resolutions
        .filter((r) => {
        if (r.decision === 'edit') {
            return (r.editedArguments == null ||
                typeof r.editedArguments !== 'object' ||
                Array.isArray(r.editedArguments));
        }
        if (r.decision === 'respond') {
            return typeof r.responseText !== 'string' || r.responseText.length === 0;
        }
        return false;
    })
        .map((r) => r.tool_call_id);
}
function resolveToolApprovalResume(payload, resolutions) {
    if (!isToolApprovalPayloadValid(payload)) {
        return { status: 400, error: 'Invalid tool approval payload' };
    }
    if (hasInvalidToolApprovalResolutions(payload, resolutions)) {
        return { status: 400, error: 'Invalid tool approval decisions' };
    }
    const undecided = findUndecidedToolCalls(payload, resolutions);
    if (undecided.length > 0) {
        return { status: 400, error: 'Every paused tool call must be decided', undecided };
    }
    const disallowed = findDisallowedDecisions(payload, resolutions);
    if (disallowed.length > 0) {
        return { status: 403, error: 'Decision not permitted for one or more tools', disallowed };
    }
    const incomplete = findIncompleteDecisions(resolutions);
    if (incomplete.length > 0) {
        return {
            status: 400,
            error: 'edit requires editedArguments and respond requires responseText',
            incomplete,
        };
    }
    return { resumeValue: mapToolApprovalResolutions(resolutions) };
}
