"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.replaceArtifactContent = exports.findAllArtifacts = exports.ARTIFACT_END = exports.ARTIFACT_START = void 0;
exports.ARTIFACT_START = ':::artifact';
exports.ARTIFACT_END = ':::';
const getLineEnd = (text, start) => {
    const index = text.indexOf('\n', start);
    return index === -1 ? text.length : index;
};
const getNextLineStart = (text, lineEnd) => lineEnd >= text.length ? text.length : lineEnd + 1;
const getCloseRange = (text, lineStart, lineEnd) => {
    const line = text.slice(lineStart, lineEnd);
    const contentStart = line.search(/\S/);
    if (contentStart === -1) {
        return null;
    }
    const markerStart = lineStart + contentStart;
    if (!text.startsWith(exports.ARTIFACT_END, markerStart) || text.startsWith(exports.ARTIFACT_START, markerStart)) {
        return null;
    }
    return {
        start: markerStart,
        end: markerStart + exports.ARTIFACT_END.length,
    };
};
const getCodeFence = (line) => {
    const match = line.trimStart().match(/^(`{3,}|~{3,})/);
    if (!match) {
        return null;
    }
    return {
        marker: match[1][0],
        length: match[1].length,
    };
};
const isClosingCodeFence = (line, openingFence) => {
    const closePattern = new RegExp(`^\\${openingFence.marker}{${openingFence.length},}\\s*$`);
    return closePattern.test(line.trim());
};
const findArtifactClose = (text, start) => {
    const openingLineEnd = getLineEnd(text, start);
    let currentIndex = getNextLineStart(text, openingLineEnd);
    let codeFence = null;
    let fallbackClose = null;
    while (currentIndex < text.length) {
        const lineEnd = getLineEnd(text, currentIndex);
        const line = text.slice(currentIndex, lineEnd);
        const closeRange = getCloseRange(text, currentIndex, lineEnd);
        if (closeRange) {
            if (!codeFence) {
                return closeRange;
            }
            fallbackClose = fallbackClose ?? closeRange;
        }
        const fence = getCodeFence(line);
        if (fence && !codeFence) {
            codeFence = fence;
        }
        else if (codeFence && isClosingCodeFence(line, codeFence)) {
            codeFence = null;
            fallbackClose = null;
        }
        currentIndex = getNextLineStart(text, lineEnd);
    }
    return codeFence ? fallbackClose : null;
};
const findArtifactEnd = (text, start) => {
    return findArtifactClose(text, start)?.end ?? text.length;
};
const getOpeningCodeFence = (text, contentStart, contentEnd) => {
    const content = text.slice(contentStart, contentEnd);
    const firstContentMatch = content.match(/\S/);
    if (!firstContentMatch) {
        return null;
    }
    const fenceStart = contentStart + (firstContentMatch.index ?? 0);
    const lineEnd = getLineEnd(text, fenceStart);
    const line = text.slice(fenceStart, lineEnd);
    const fence = getCodeFence(line);
    if (!fence || !line.trimStart().startsWith(fence.marker.repeat(fence.length))) {
        return null;
    }
    return {
        ...fence,
        contentStart: getNextLineStart(text, lineEnd),
    };
};
const findClosingCodeFenceStart = (text, start, end, openingFence) => {
    let currentIndex = start;
    while (currentIndex < end) {
        const lineEnd = getLineEnd(text, currentIndex);
        const line = text.slice(currentIndex, lineEnd);
        if (isClosingCodeFence(line, openingFence)) {
            return currentIndex;
        }
        currentIndex = getNextLineStart(text, lineEnd);
    }
    return -1;
};
const getSearchRange = (artifactContent) => {
    const openingLineEnd = getLineEnd(artifactContent, artifactContent.indexOf(exports.ARTIFACT_START));
    if (openingLineEnd >= artifactContent.length) {
        return null;
    }
    const contentStart = getNextLineStart(artifactContent, openingLineEnd);
    const artifactClose = findArtifactClose(artifactContent, 0);
    const contentEnd = artifactClose?.start ?? artifactContent.length;
    const openingFence = getOpeningCodeFence(artifactContent, contentStart, contentEnd);
    if (!openingFence) {
        return { searchStart: contentStart, searchEnd: contentEnd };
    }
    const closingFenceStart = findClosingCodeFenceStart(artifactContent, openingFence.contentStart, contentEnd, openingFence);
    if (closingFenceStart === -1) {
        return { searchStart: openingFence.contentStart, searchEnd: contentEnd };
    }
    const closingLineEnd = getLineEnd(artifactContent, closingFenceStart);
    const trailingContent = artifactContent.slice(closingLineEnd, contentEnd);
    if (trailingContent.trim().length > 0) {
        return { searchStart: contentStart, searchEnd: contentEnd };
    }
    const searchEnd = artifactContent[closingFenceStart - 1] === '\n' ? closingFenceStart - 1 : closingFenceStart;
    return { searchStart: openingFence.contentStart, searchEnd };
};
const replaceRange = (originalText, start, end, updated) => {
    const endText = originalText.substring(end);
    const separator = endText.startsWith('\n') || updated.endsWith('\n') ? '' : '\n';
    return originalText.substring(0, start) + updated + separator + endText;
};
const isClosingArtifactFenceAt = (text, start) => {
    const marker = text[start];
    if (marker !== '`' && marker !== '~') {
        return false;
    }
    let markerEnd = start + 1;
    while (markerEnd < text.length && text[markerEnd] === marker) {
        markerEnd++;
    }
    if (markerEnd - start < 3) {
        return false;
    }
    let hasLineBreak = false;
    for (let i = markerEnd; i < text.length; i++) {
        if (text[i] === '\n') {
            hasLineBreak = true;
            continue;
        }
        if (/\s/.test(text[i])) {
            continue;
        }
        return hasLineBreak && text.startsWith(exports.ARTIFACT_END, i);
    }
    return false;
};
const normalizeBeforeClosingArtifactFence = (text) => text.replace(/\n{2,}/g, (newlines, offset) => isClosingArtifactFenceAt(text, offset + newlines.length) ? '\n' : newlines);
const findAllArtifacts = (message) => {
    const artifacts = [];
    if (message.content?.length) {
        message.content.forEach((part, partIndex) => {
            if (part.type !== 'text' || typeof part.text !== 'string') {
                return;
            }
            let currentIndex = 0;
            let start = part.text.indexOf(exports.ARTIFACT_START, currentIndex);
            while (start !== -1) {
                const end = findArtifactEnd(part.text, start);
                artifacts.push({
                    start,
                    end,
                    source: 'content',
                    partIndex,
                    text: part.text,
                });
                currentIndex = end;
                start = part.text.indexOf(exports.ARTIFACT_START, currentIndex);
            }
        });
    }
    if (!artifacts.length && message.text) {
        let currentIndex = 0;
        let start = message.text.indexOf(exports.ARTIFACT_START, currentIndex);
        while (start !== -1) {
            const end = findArtifactEnd(message.text, start);
            artifacts.push({
                start,
                end,
                source: 'text',
                text: message.text,
            });
            currentIndex = end;
            start = message.text.indexOf(exports.ARTIFACT_START, currentIndex);
        }
    }
    return artifacts;
};
exports.findAllArtifacts = findAllArtifacts;
const replaceArtifactContent = (originalText, artifact, original, updated) => {
    const artifactContent = artifact.text.substring(artifact.start, artifact.end);
    const range = getSearchRange(artifactContent);
    if (!range) {
        return null;
    }
    const { searchStart, searchEnd } = range;
    const innerContent = artifactContent.substring(searchStart, searchEnd);
    const originalTrimmed = original.replace(/\n$/, '');
    const relativeIndex = originalTrimmed === '' && innerContent.trim().length > 0
        ? -1
        : innerContent.indexOf(originalTrimmed);
    if (relativeIndex === -1) {
        return null;
    }
    const absoluteIndex = artifact.start + searchStart + relativeIndex;
    return normalizeBeforeClosingArtifactFence(replaceRange(originalText, absoluteIndex, absoluteIndex + originalTrimmed.length, updated));
};
exports.replaceArtifactContent = replaceArtifactContent;
