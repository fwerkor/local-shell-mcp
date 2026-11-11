# Durable checkpoint storage port

Source baseline: LibreChat `e8f3be08623663d4ad7f7241e693c94469b63bb0`,
`packages/api/src/agents/checkpointer.ts` and `checkpoints/saver.ts`, plus
`@langchain/langgraph-checkpoint 1.1.3` pending-write slot constants.

`webui/checkpoints.py` implements the storage seam, not a replacement graph
scheduler. It preserves checkpoint/channel state as JSON, parent references,
per-owner/per-generation root and nested namespaces, pending writes keyed by
`task_id` and index, original special-channel indexes, and completed sibling
bookkeeping. Normal pending writes use first-write-wins; all-special batches
replace their reserved slots, matching the original saver. It supports the
original durable event-actor exception and interrupt/real-channel anchoring.

SQLite replaces MongoDB behind the interface. Two lazily created tables live in
the existing `lsm.sqlite3`. Owner isolation uses separate SQL key columns rather
than concatenated Mongo key prefixes. Bookkeeping batches stage transactionally
in hidden incomplete heads rather than an in-memory buffer. A clean exit removes
these rows, expired unfinished heads are pruned, and a reader cannot resume until
the checkpoint payload is present. This avoids a second database or process.

The retained 15 MiB checkpoint ceiling and 8 MiB warning are conservative bounds
from the source. SQLite stores JSON state and metadata once, so Mongo's duplicate
BSON metadata accounting is deliberately inapplicable. Native LangChain class
serialization is not implemented here: runtime adapters must pass JSON message
and channel state, including serializable tool-call/result objects.

Runtime integration:

```python
saver = SQLiteCheckpointSaver(database, owner)
base = saver.config(conversation_id, generation_id, event_actor=True)
current = saver.put(base, {
    "id": checkpoint_id,
    "channel_values": {"messages": assistant_and_prior_messages},
    "channel_versions": channel_versions,
    "versions_seen": versions_seen,
}, {"source": "loop", "step": step})
saver.put_writes(current, [("messages", completed_tool_message)], call_id)
# Reopen after disconnect/restart; source pending writes identify completed work.
restored = saver.get_tuple(current)
```

Never claim exactly-once tool side effects: a process can fail after an external
side effect and before its result write. The original saver and LangGraph have
the same boundary. A stored result must be matched to its original proposal and
current permissions must still be checked before any unfinished call executes.

Validation: 57 original-Node differential anchor cases and original namespace
round-trip functions; actual SQLite reopen, concurrent write contention, atomic
failure rollback, owner/generation/nested scope isolation, completed sibling and
interrupt persistence, TTL cleanup, and size bounds. The saver module tests cover
100% of statements and branches. This does not establish full Graph/ToolNode,
provider, approval, cancellation, or event-actor runtime equivalence.
