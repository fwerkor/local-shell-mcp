# Hosted Chat (optional)

Hosted Chat is a self-hosted, BYOK chat and MCP Apps client integrated into LSM's human interface. It is **not** a Logical Session mode: conversations have independent identities and can optionally attach an existing LSM Logical Session. ChatGPT and other external clients continue working with the same LSM Sessions and tools.

## Enable

Hosted Chat is disabled by default. Set:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Restart the Controller and open **Hosted Chat** immediately beneath the Web UI / TUI selector. The feature also has a mobile top-bar entry. The chat host uses the existing LSM OAuth identity and scopes. The same controller operates the MCP server used by the model's tool loop; Workers cannot initiate execution.

## Model profiles

Choose **Model profiles** to create/edit a profile with a name, HTTPS OpenAI-compatible API base URL, model ID and optional API Key. Multiple profiles can coexist and conversations can switch models.

Profiles, conversations, complete message history and tool-call results are **saved on the server** via the configured LSM state backend. Their scope is tied to the authenticated principal. The API Key is encrypted with AES-GCM and is never returned from profile-list or profile-detail endpoints. It is not stored in browser storage, sent to the model as a prompt, or included in audit logs. The chat host passes it only to the chosen model API.

The first file-backed deployment creates `hosted-chat-encryption-key` in the state directory with mode 0600. **Back up this file alongside the state data. Without it, saved API Keys cannot be decrypted.** If the Controller uses Redis, multiple replicas, or another non-file state backend, configure a stable, shared 32-byte URL-safe-base64 key:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

Do not rotate this setting without migrating the encrypted profiles. Do not use in-memory state storage when durable conversations are required.

By default, only HTTPS model endpoints with DNS hostnames are accepted; local/private endpoints and HTTP are refused to reduce server-side request forgery risk. Administrators deliberately hosting a trusted private model gateway can opt in:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

Do not enable this on an untrusted multi-user Controller unless users are authorized to contact internal services.

## Conversations and MCP Apps

Create a conversation using a saved model profile. Each submitted turn becomes a server-owned background task; closing the browser does not cancel the task. Completed text and tool calls are checkpointed durably between model/tool steps. Stop explicitly to interrupt. On Controller restart, interrupted runs are marked as such and can be continued in a new turn, but **unknown-outcome tool calls are never automatically replayed**.

Open **Archived conversations** beneath the chat list to browse older chats separately. **Archive** moves an idle conversation out of the regular list into independent `.json.zst` storage using the existing Audit zstd codec (no extra dependency). Only lightweight metadata is kept alongside the compressed record for the archive browser; the original messages and tool events remain losslessly recoverable. Archived chats are omitted from the normal conversation list and any normal-list searches, and are **not included in full-text search indexing**. The archive view offers its own title-only filter, but does not build a search index of archived content. Select an archive to read it in read-only mode, or **Restore** to move it back to active conversations and continue chatting. Archiving a running turn is rejected. Explicitly deleting an archive is permanent. Archive writes precede removal of the active copy, and restoring writes the active copy before removing the archive to avoid data loss after crashes. Zstd compression is independent of whether the filesystem uses ZFS.

### Long conversations and context compact

The original messages and tool activity are always preserved in server storage. Each **Model profile** has a configurable **Context window (tokens)**, defaulting to **32,768** (range 8,192–1,000,000). An internal conservative token estimate (UTF-8 bytes rather than provider-specific tokenization) includes system instructions, model-visible history and MCP tool definitions. When estimated input approaches **80%** of the configured window, the controller automatically summarizes older completed turns using the **same configured model and endpoint**, with no added tokenizer or summarization dependency. The recap retains goals, constraints, decisions, modified paths, tool outcomes and next steps. It is stored durably as a separate context checkpoint (`context.summary` and `context.through`). Only the recap plus a bounded tail of original conversation messages is sent to the model. Older raw messages are never deleted, modified or inserted into the summary as system instructions. Within an Agent Loop, context is re-evaluated between model requests after tool results.

The **Compact** button in the conversation toolbar explicitly requests a recap, even before the automatic threshold; the conversation must not be running. The saved summary can be inspected in the context section above the chat history. A failed summarization leaves the previous context checkpoint and full conversation unchanged. The approximate estimator does not guarantee the exact provider token count, so select the context window actually supported by your model. A single oversized active turn that cannot fit is rejected rather than silently truncated. There is no automatic truncation at 64 messages.

Tool calls are sent through LSM's authenticated MCP endpoint, preserving all ordinary tool permissions and audit/preflight behavior.

Open **Live Workspace** to render LSM's existing `workspace_open` MCP Apps resource inside an embedded view. The host uses the `@modelcontextprotocol/ext-apps` bridge for app lifecycle, credential renewal, tool calls and human-to-agent actions. No second file manager, terminal, audit or job UI is implemented.

The optional attached `session_id` lets Hosted Chat use and display an existing Logical Session; it does not reclassify the Session or give Hosted Chat ownership of it. Chat conversation identifiers and Logical Session identifiers are separate.

## Boundaries

- Model requests use OpenAI-compatible Chat Completions with tool calling; other provider protocols require an adapter.
- Per-turn safeguards cap model iterations and tool calls. Longer tasks may be continued in a new turn using the durable history.
- Chat conversation deletion is explicit. No automatic history eviction is performed.
- The Controller must be network-reachable by its own MCP client and the browser must be authorized for the LSM Live Workspace API.
