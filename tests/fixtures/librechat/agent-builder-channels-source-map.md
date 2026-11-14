# Python WebUI: Agent Builder, Settings and named model channels

Pinned behavior baseline: LibreChat `e8f3be08623663d4ad7f7241e693c94469b63bb0` (v0.8.8); the originally integrated `@librechat/agents@4.0.1` (`c4ffb9b1b78421bf63eba3e56993017f922387f3`). The source is available locally at `/root/librechat-reference-e8f3be08` and `/root/librechat-agents-reference` for parity reviews, but these paths are **not** production dependencies.

## Authoring/storage/runtime field map

All persisted Agent fields live as validated JSON in SQLite `agents.config` (and immutable `agent_versions.snapshot` revisions); the API is Python `agent_routes.py`, persistence `agents.py`, validation `agent_validation.py`. The frontend remains the original React `client/src/components/SidePanel/Agents/AgentPanel.tsx`, `ModelPanel.tsx`, `Tools/*`, and `Advanced/*` where applicable.

| Original Builder field or section | Server mapping | Runtime meaning / current boundary |
| --- | --- | --- |
| `name`, `description`, `avatar`, `category`, `support_contact` | `clean_agent_config` → `agents.config` | Builder/display metadata; avatar upload handled as an attachment operation |
| `instructions` | `agents.config` → `generation_routes._start_task` | Prepended as system instruction for a fresh Agent run |
| `provider`, `model` | `agents.config` → `selected_provider`, `provider_config` | Exact named channel identity and model, used on first run, handoff, resumed run and persistently stored run state |
| `model_parameters` | Source-compatible numeric cleaning (`sanitize_model_parameters`) → `AgentContext.parameters` | `temperature`, `max_tokens`/`maxTokens`/`max_output_tokens`/`maxOutputTokens`, `top_p`/`topP` passed to actual provider HTTP request; max output tokens clamped 1–16384, temperature 0–2, top-p 0–1. Unrecognized optional parameters remain in authoring JSON but are not sent; see limitations below |
| `tools`, `tool_options` | JSON validation and persisted per-tool preferences | `tools` gates Agent's offered LSM registry, MCP and Ask User tools; **permission checks are independent**. Advanced `tool_options` are retained for compatibility but background/deferred/code-execution caller execution needs its own runtime owner |
| `agent_ids`, `subagents`, `edges` | Original topology/reference validation, owner check | `build_subagent_configs`/`handoff`/graph runtime own execution; no protocol reimplementation here |
| `recursion_limit`, `end_after_tools` | `AgentRunner._context` → `AgentContext`, `run_agent_loop` | Recursion ceiling and stop-after-tools execution, respectively |
| `hide_sequential_outputs` | Builder/SQLite | Preserved; UI activity-stream postprocessing still needs the graph runtime to implement full original behavior |
| `tool_resources`, `conversation_starters` | Validated and persisted; resource refs checked for ownership | Attachments and file/knowledge processing delegated to attachment owner; starters shown in UI |
| `skills`, `skills_enabled`, `skill_authoring_enabled`, `skills_scope` | Validated and persisted | Skills execution and catalog are separate runtime work; no unsupported skills capability advertised here |
| `memory_scope` | Validated `user`/`agent`, persisted | Memory runtime owner must apply per-Agent partitioning and `set_memory`/`delete_memory`; not implemented by channel configuration |
| `stateful_code_sessions`, `stateful_code_environment`, `code_environment_id`, `code_workspace_id`, `repositoryInstructions`, `git_identity` | Validated and persisted | Session/workspace runtime must enforce these; native LSM shell registry does not implicitly implement LibreChat sandbox workflows |
| `artifacts` | Validated and persisted | Artifact UI feature; does not imply executable image/code artifact provider capability |
| Version list, revert, duplicate | `agent_versions` and `AgentRepository.{versions,revert,duplicate}` | Snapshot restores validated Agent references and tool choices; version API does not contain model-channel secrets |

The source contract for Agent authoring comes from LibreChat `client/src/components/SidePanel/Agents/AgentPanel.tsx` (`composeAgentUpdatePayload`), `client/src/components/SidePanel/Agents/Tools/items/capabilities.ts`, data schemas `packages/data-schemas/src/methods/agent.ts`, and agent validation/parsing. Oracle tests: `tests/test_webui_agent_config_source.py` and `tests/fixtures/librechat/agent_*`.

## Named-channel mapping and compatibility

| Original source | Python / SQLite mapping | Notes |
| --- | --- | --- |
| LibreChat `packages/data-provider/src/config.ts` `endpointSchema` | `provider_profiles._validate`, `/api/lsm/providers`, SQLite `settings` | Original `name` is a separate endpoint identity; original custom `provider` supports `anthropic` **only** as the native exception; otherwise default is OpenAI-compatible |
| Original `models.default`, `baseURL`, `apiKey` | `models`, `base_url`, `api_key` | Separate credentials/catalog/URL per channel; secrets only server-side |
| Built-in legacy endpoint entries | `model.provider.openai`, `.anthropic`, `.google` | **Unchanged**, existing SQLite rows and environment defaults used as-is; old PUT payload without `name` still works |
| New endpoint entries | `model.channel.<name>` | Independent named provider type (`openai`, `anthropic` or `google`), immutable type per name; at most 64 unique named channels |
| Model catalog + endpoint selector | `config_routes._endpoint_models`/`_endpoint_info`; React `ModelProviders.tsx` | `api/models` exposes each name as its own catalog key; `api/endpoints` exposes each as its own endpoint with protocol-specific `type`; Agent Provider combobox uses these names |
| Provider dispatch | `selected_provider` → `provider_config` → `stream_model`/`stream_model_with_tools`/`provider_tool_protocols` | OpenAI-compatible `/chat/completions`, native Anthropic `/messages`, and LSM's explicit native Gemini `:streamGenerateContent` with tool message conversion; this does not make a custom OpenAI endpoint a generic arbitrary native protocol |
| Endpoint administration | `GET`, `PUT`, `DELETE /api/lsm/providers` | Admin scope `admin:config` plus normal auth/same-origin checks. Name cannot impersonate built-ins. Omitted/empty key retains prior credential, write is transactional; delete refuses referenced Agent, run or conversation |
| Existing chats/presets | Persist exact `endpoint`/`provider` names, older names unchanged | New channels are additive, and changing credentials does not rewrite old messages or runs; users may retain built-in selections without any data conversion |

## Advertised tool capability versus execution authorization

`/api/endpoints.agents.capabilities` exposes only the currently backed optional Agent features (LSM registry tools, subagents, chain, Ask User, end-after-tools). This capability list controls Builder visibility, **not** machine scopes. `/api/agents/tools` is a registry-based catalog regardless of machine access; `AgentRunner._context` produces the available runtime tools using the active machine ACL and conversation scopes; `lsm_tool_registry.call_tool` rechecks every concrete machine action. `session_manage`/`plan_manage` are available without granting a machine, while administrative actions require `local=write` plus appropriate scopes. MCP tools require separate MCP opt-in. No blanket machine authorization is created when enabling an Agent tool.

## Explicit limitations / handoffs

- LibreChat's custom `headers`, `addParams`, `dropParams`, `customParams`, `tokenConfig`, `fetch` and `userIdQuery` are not exposed as configurable named-channel options by LSM's admin API. Values outside the supported channel payload must not silently become HTTP headers or protocol adapters. Original `endpointSchema.provider` does not cover Gemini; LSM's named Gemini type is a **deliberate native extension**, not a claimed drop-in YAML custom Endpoint.
- Agent `tool_options` background/deferred/allowed-callers, full Memory CRUD/context compaction, Actions OpenAPI tools, Skills execution, `hide_sequential_outputs`, and stateful code environment are not implemented by this channels task. Their owners must consume the already-preserved source-compatible fields; these switches must not grant execution privileges or be described as fully supported yet.
- Numeric output handling currently transmits `temperature`, `top_p`, and max output length. Other optional model parameters need provider-specific allowlists and per-protocol conformance; they are not guaranteed to have an execution effect merely because the original Builder persists them.
- User-entered API key values are intentionally plaintext in the existing protected local SQLite settings database so the Python provider client can use them, but never enter ordinary profile reads, endpoints/models listings, logs, generation SSE, or model-visible Agent parameters. Protect the Controller data directory and its backups.

## Test evidence

- Authoring source and numeric oracle: `tests/test_webui_agent_config_source.py`.
- Same-type channel isolation, legacy-state migration, restart, protocol routing, validation, deletion safety and secret redaction: `tests/test_webui_provider_profiles.py`.
- Existing full-provider streaming, native model transport, runtime permission enforcement and source graph tests: `tests/test_webui_provider_edgecases.py`, `tests/test_webui_providers.py`, `tests/test_webui_agent_runtime.py`, `tests/test_webui_generation_runtime_edges.py`.
- React browser first-launch and model provider smoke: `tests/test_webui_provider_browser.py`; named channel browser scenario is added separately when assets are available.

Do not restore Node/Mongo, `integrations/`, or LibreChat's independent execution stack. The React workspace is a build-time source only; the Controller and Worker remain Python SQLite-native and lightweight.
