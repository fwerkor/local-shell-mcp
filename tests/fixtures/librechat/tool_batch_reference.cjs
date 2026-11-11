// Original agents functions; see LICENSE.agents and source_hashes.json.
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.stableStringify = stableStringify;
exports.recordArgsEqual = recordArgsEqual;
function directReplayKey(call, batchIndex) {
    return call.id == null || call.id === ''
        ? JSON.stringify(['position', batchIndex])
        : JSON.stringify(['id', call.id]);
}
function stableStringify(value) {
    if (Array.isArray(value)) {
        return `[${value.map((item) => stableStringify(item)).join(',')}]`;
    }
    if (value !== null && typeof value === 'object') {
        const record = value;
        const keys = Object.keys(record).sort();
        return `{${keys
            .map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`)
            .join(',')}}`;
    }
    return JSON.stringify(value);
}
function recordArgsEqual(left, right) {
    return stableStringify(left) === stableStringify(right);
}
exports.directReplayKey = directReplayKey;
