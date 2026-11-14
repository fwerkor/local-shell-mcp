// Derived from LibreChat e8f3be08, ISC license; exact TS bodies.
const ContentTypes={SUMMARY:"summary",TEXT:"text",ERROR:"error"}; const ErrorTypes={COMPACTION_FAILED:"compaction_failed"};
function getSummaryPartText(part) {
  if (part?.type !== ContentTypes.SUMMARY) {
    return "";
  }
  const content = part.content;
  if (typeof content === "string") {
    return content.trim();
  }
  if (Array.isArray(content)) {
    let text = "";
    for (const block of content) {
      if (block != null && typeof block === "object" && "text" in block) {
        text += typeof block.text === "string" ? block.text : "";
      }
    }
    return text.trim();
  }
  return "text" in part && typeof part.text === "string" ? part.text.trim() : "";
}
function isUsableSummaryPart(part) {
  if (part == null || typeof part !== "object" || !("type" in part)) {
    return false;
  }
  if (part.type !== ContentTypes.SUMMARY) {
    return false;
  }
  const summary = part;
  if (summary.failed === true || summary.summarizing === true) {
    return false;
  }
  if (Array.isArray(summary.content) && summary.boundary == null) {
    return false;
  }
  return getSummaryPartText(summary).length > 0;
}
function findCheckpointSummaryPart(content) {
  if (!Array.isArray(content)) {
    return null;
  }
  let checkpoint = null;
  for (const part of content) {
    if (isUsableSummaryPart(part)) {
      checkpoint = part;
    }
  }
  return checkpoint;
}
function resolveCheckpointMessage(message) {
  const summaryPart = findCheckpointSummaryPart(message.content);
  if (summaryPart != null && Array.isArray(message.content)) {
    const summaryIndex = message.content.lastIndexOf(summaryPart);
    return summaryIndex === 0 ? message : { ...message, content: message.content.slice(summaryIndex), tokenCount: undefined };
  }
  if (!message.summary) {
    return null;
  }
  return {
    ...message,
    role: "system",
    content: [{ type: ContentTypes.TEXT, text: message.summary }],
    tokenCount: message.summaryTokenCount ?? message.tokenCount
  };
}
function getLatestEventActorSummary(contentParts) {
  if (!Array.isArray(contentParts)) {
    return;
  }
  for (let index = contentParts.length - 1;index >= 0; index -= 1) {
    const part = contentParts[index];
    if (!isUsableSummaryPart(part)) {
      continue;
    }
    const tokenCount = part.tokenCount;
    return createAgentEventActorSummary({
      text: getSummaryPartText(part),
      tokenCount: typeof tokenCount === "number" && Number.isFinite(tokenCount) && tokenCount >= 0 ? tokenCount : 0
    });
  }
  return;
}
const COMPACTION_FAILED_ERROR = JSON.stringify({ type: ErrorTypes.COMPACTION_FAILED });
function compactionFailureContent(errorText = COMPACTION_FAILED_ERROR) {
  return [{ type: ContentTypes.ERROR, error: errorText, initiatedBy: "user" }];
}
function resolveFailedTurnContent(requestBody, errorText) {
  if (requestBody?.compact !== true) {
    return {};
  }
  return { content: compactionFailureContent(errorText) };
}
function markCompactionOutcome(contentParts, { aborted = false } = {}) {
  const summary = contentParts.find(isUsableSummaryPart);
  if (summary != null) {
    summary.initiatedBy = "user";
    return;
  }
  let markedFailure = false;
  for (const part of contentParts) {
    if (part?.type === ContentTypes.ERROR) {
      part.initiatedBy = "user";
      markedFailure = true;
    }
  }
  if (markedFailure) {
    return;
  }
  if (aborted) {
    throw Object.assign(new Error(COMPACTION_FAILED_ERROR), { code: "COMPACTION_FAILED" });
  }
  for (let index = contentParts.length - 1;index >= 0; index -= 1) {
    if (contentParts[index]?.type === ContentTypes.SUMMARY) {
      contentParts.splice(index, 1);
    }
  }
  contentParts.push(...compactionFailureContent());
}
function isSummaryPartWithText(part) {
  if (part == null || typeof part !== "object" || !("type" in part)) {
    return false;
  }
  if (part.type !== ContentTypes.SUMMARY) {
    return false;
  }
  const summary = part;
  return getSummaryPartText(summary).length > 0;
}
function withoutUnusableSummaryParts(content) {
  const filtered = content.filter((part) => isUsableSummaryPart(part) || !isSummaryPartWithText(part));
  return filtered.length === content.length ? content : filtered;
}
function dropUnusableSummaryParts(message) {
  const content = message?.content;
  if (!Array.isArray(content)) {
    return false;
  }
  const filtered = withoutUnusableSummaryParts(content);
  if (filtered === content) {
    return false;
  }
  message.content = filtered;
  return true;
}
function stripUnusableSummaryParts(payload) {
  if (!Array.isArray(payload)) {
    return payload;
  }
  let changed = false;
  const result = payload.map((message) => {
    const content = message?.content;
    if (!Array.isArray(content)) {
      return message;
    }
    const filtered = withoutUnusableSummaryParts(content);
    if (filtered === content) {
      return message;
    }
    changed = true;
    return { ...message, content: filtered };
  });
  return changed ? result : payload;
}

module.exports={getSummaryPartText,isUsableSummaryPart,findCheckpointSummaryPart,resolveCheckpointMessage,resolveFailedTurnContent,markCompactionOutcome,dropUnusableSummaryParts,stripUnusableSummaryParts};
