# Channels and models

## Set up a channel

Open the model selector in Chat and enter channel management. Select **Add channel**, choose the connection type, enter the required information, and save. Select a model from that channel for a new chat. For a custom Agent, select the channel and model in the Agent configuration instead.

Channels are Controller-owned rather than personal chat settings. In authenticated deployments, channel management requires the `admin:config` scope. An administrator can configure shared channels without distributing API keys to chat users.

A normal API channel has a name, provider protocol, base URL, credentials and model identifiers. Use an API key issued for the selected endpoint, not the password of your LSM account. LSM makes requests from the Controller; a URL that works from your laptop may not work from the Controller.

| Protocol | Example API base URL | Use |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | OpenAI-compatible chat gateways and local inference servers |
| OpenAI Responses | `https://api.openai.com/v1` | A gateway exposing the Responses API |
| Anthropic native | `https://api.anthropic.com/v1` | Anthropic Messages-compatible APIs |
| Google Gemini native | `https://generativelanguage.googleapis.com/v1beta` | Gemini generateContent-compatible APIs |

Use the base URL required by the provider, rather than pasting a full generation request URL such as a URL ending in `/chat/completions`. A gateway claiming OpenAI compatibility might support Chat Completions but not Responses, tool calls, streaming usage, multimodal input or reasoning options. Choose the protocol it actually supports. Example URLs are protocol examples, not a promise of free access or availability.

## Local and custom endpoints

For an OpenAI-compatible server listening on the Controller itself, the base URL might be `http://127.0.0.1:8080/v1`. When running in Docker, loopback refers to that container, not the physical host. Use an address reachable from the Controller's network namespace. A remote Worker registration alone does not make its inference API reachable.

The model URL validator requires HTTPS, except for HTTP on literal loopback hosts (`localhost`, `127.0.0.1`, `::1`). An HTTP endpoint on a LAN address or Docker service name must be exposed through an HTTPS gateway; the retired Hosted Chat private-endpoint toggle is not applicable. Base URLs must not include embedded credentials, fragments or query strings.

Use TLS for remote endpoints, restrict access to trusted private gateways, and check model identifiers against the inference server. Never put API keys in prompts, screenshots, query strings or published configuration. Leave the API key blank when editing an existing channel to preserve its saved key; only use a keyless connection when the service supports it.

## Environment-configured defaults

The built-in OpenAI profile can be configured before launch using `LOCAL_SHELL_MCP_MODEL_BASE_URL` (or `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL` and `LOCAL_SHELL_MCP_MODEL_API_KEY` (or `OPENAI_API_KEY`). The built-in Anthropic and Google profiles can read `ANTHROPIC_API_KEY` and `GOOGLE_KEY` / `GOOGLE_API_KEY` respectively. Saved built-in profiles take precedence over their environment-derived fallback; use named channels for multiple independent endpoints. Environment-configured defaults are not an alternative to protecting service secrets.

## ChatGPT account authorization

The account/Codex channel uses a supported ChatGPT account authorization flow rather than an ordinary API key. Start authorization from channel management and sign in on the official authorization page. On a local deployment the callback can complete automatically. If the browser cannot reach the loopback listener, copy the entire callback URL from its address bar and paste it into the authorization dialog. A connection failure at the loopback address is expected in this manual flow.

Treat the callback URL as a credential; never send it in a chat or post it publicly. The Controller stores authorization on the server and refreshes credentials when possible. Reauthorize if the account expires or access is revoked. Available models, plan limits and permitted usage are determined by the upstream account service; LSM does not provide additional subscription quota.

## Model discovery and context limits

Enable automatic discovery to request model information from the provider. The Controller refreshes it periodically (currently every ten minutes); a manual refresh is also available. Failed discovery retains previously saved model data. If the provider lacks a compatible model-list endpoint, turn off discovery and enter model identifiers manually, one per line.

Specify the context window for each model when it is known. An explicit per-model value overrides discovered metadata or fills a missing value. The editor accepts 1 to 2,000,000 tokens; this is a configuration range, not a guarantee that a provider supports that capacity. Use the effective limit for your deployment, accounting for server-side configuration and the model's own limits.

## Sampling, reasoning and usage

Channel/model defaults control the request parameters supported by the selected provider. The chat composer may expose reasoning effort where available. Different protocols implement sampling and reasoning differently; an option may be unsupported by a particular model. Begin with provider defaults, then change one setting at a time.

LSM can request exact streaming token usage and fall back when the provider explicitly rejects the usage option. An endpoint that does not return usage cannot provide exact billing or cache statistics. See [Memory and context](context.md) for the distinction between cumulative consumption and current context capacity.

## Changing and deleting channels

A conversation retains its selected model/Agent and history. Switch the model deliberately when changing endpoints or debugging a provider issue. Renaming an in-use channel is restricted to protect references. Deleting an in-use channel requires additional confirmation: history remains, but Agents and chats referencing the deleted channel must select a working replacement before further execution.

Channel settings are server-side, not a browser-only preset. Credentials are not returned through ordinary channel catalog responses. Protect the Controller state directory and backups as credential-bearing data.

## Connection checklist

1. Confirm the Controller can reach the API host and that TLS validates.
2. Confirm the base path, protocol, credential and exact model ID.
3. Refresh discovery or enter one known model manually.
4. Send a short plain-text prompt, then test a small tool call.
5. Check error details for the upstream HTTP status, timeout or unsupported option; do not repeatedly retry invalid credentials.

See [Administration and troubleshooting](administration.md) for handling rate limits, streaming interruption and authorization errors.
