# Memory, context and token usage

## Three different kinds of state

| State | Purpose |
|---|---|
| Conversation history | Original messages and tool activity saved by the Controller |
| Context window | The subset of instructions, tool schemas, history, summaries and other data sent in a particular model request |
| Persistent memory | Reusable facts and preferences accessible across conversations in the relevant memory scope |

A long saved conversation can exceed the model's context window without losing all its history. Memory does not mean that the entire account history is sent to every model request.

## Manage memory

Memory is enabled by default unless disabled by the user's settings, the chat toggle or deployment/Agent capability restrictions. Use the memory management page to inspect and edit stored entries. Ask the Agent to remember useful facts, project conventions or preferences, and verify the result in the memory interface.

Memory can use a shared personal pool or an Agent-specific scope, depending on Agent configuration. Do not store API keys, passwords or unnecessary sensitive data in memory. Turning memory off prevents its use in the relevant scope; it is not the same as deleting existing stored entries or removing mentions from conversation history.

When exposed, the model uses `set_memory` to create or update an entry; an empty value removes it. `find_memory` retrieves entries by query or exact key, and an empty query lists saved memories. The optional `include_conversations` flag searches text from other conversations as well. Pagination uses `page` (default 1) and `limit` (default 10, maximum 50). This history retrieval searches conversation text rather than raw tool invocation records. Retrieval is relevance-ranked, so use precise names or terms and refine the query if necessary.

Automatic memory/Skill injection is held stable across turns of a conversation to preserve reusable provider prompt prefixes. Editing stored memory does not retroactively rewrite the already injected snapshot. Explicit memory retrieval accesses current stored data; start a new conversation if you need newly injected context.

## Context capacity

Set each model's actual context limit in its channel. The Controller estimates the model-visible input and reserves room for output; the current budget implementation defaults to an 85% compaction ratio and 5% reserve ratio, subject to effective model and runtime configuration. The count may be approximate for an unfamiliar tokenizer, multimodal request or provider-specific schema.

The context composition can include system instructions, Agent configuration, tool definitions, attachments, prior messages and tool results. A provider may use a different tokenizer or count additional internal tokens. Treat the display as operational guidance, not a provider admission guarantee.

## Automatic compaction

When a context budget requires compaction, the Controller creates or updates a checkpoint summary of older context and retains recent history for subsequent model requests. The summary attempts to preserve the objective, constraints, decisions, progress, relevant identifiers, tool outcomes and next actions. The original saved history remains available for inspection; the summary is a model-generated approximation, not a perfect reproduction.

Compaction runs before the next request requiring the reduced context. If summarization fails, the engine retries according to its error handling and should not simply proceed using an already oversized input. Review the compaction status and detailed error if it cannot continue. Recent messages and tool-call/result relationships must remain coherent. Completed old tool results are not progressively rewritten merely to shrink context.

A single enormous attachment or tool result can still exceed the budget. Ask for bounded output, file ranges or a digest; save large results to files and retrieve specific parts instead of repeatedly inserting them into model context.

## Cumulative usage and cache hits

The session usage display and context window answer different questions. Input/output usage accumulates across model requests in the conversation, including repeated context. Cache metrics describe provider-reported prompt caching when available. Context occupancy measures the active model's window and does not sum every past request.

For example, a request containing 20,000 input tokens followed by another request containing 25,000 input tokens consumes 45,000 cumulative input tokens, but the second request uses approximately 25,000 input tokens of its current context capacity. Cached tokens are not free unless the provider's pricing says so. A larger model context limit changes capacity, not previously consumed usage.

Compaction can lower current occupancy while adding model consumption. Switching models changes the applicable context limit; it does not erase earlier consumption. If a provider omits exact usage or cache metadata, the estimates and metrics may be incomplete. For financial reconciliation use the provider's billing data and pricing, not just the LSM display.

## Reduce cost and preserve useful context

Keep stable Agent instructions, avoid unnecessary large tool outputs, and use focused retrieval. Start a separate conversation for unrelated work. When handoff is necessary, save a concise checkpoint with exact paths, commit IDs, observed results and open questions. Verify important facts against the original source or tool result rather than relying solely on a generated summary.
