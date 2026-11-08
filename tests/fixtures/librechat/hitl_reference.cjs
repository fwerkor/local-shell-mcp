// Original LibreChat functions; see LICENSE.LibreChat and source_hashes.json.
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.mapToolApprovalResolutions = mapToolApprovalResolutions;
exports.mapAskUserAnswer = mapAskUserAnswer;
exports.mapAskUserAnswers = mapAskUserAnswers;
exports.resolveAskUserQuestionResume = resolveAskUserQuestionResume;
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
