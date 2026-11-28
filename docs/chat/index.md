# WebUI Chat

LSM WebUI Chat is a self-hosted AI agent workspace built into the Controller. Bring your own model endpoint or a supported account, and give the model access to your own tools and machines. No external MCP client is required. External clients can still connect to the same Controller independently.

## How the pieces fit together

- **Controller:** the Python service that hosts the browser application, model requests, tool execution, scheduling and persistent state.
- **Channel:** a model API connection or supported account authorization, with its own credentials, protocol, model list and settings.
- **Model:** a model identifier within a channel. The same identifier on two channels does not imply the same endpoint.
- **Agent:** a reusable configuration combining a model, instructions, tools, Skills and permissions.
- **Conversation:** saved messages, settings, execution history and model/Agent association.
- **Project:** a group of conversations with shared defaults.
- **Worker:** an outbound-connected execution target. It is not a model provider or a separate chat server.
- **Logical Session:** durable tool-side task identity, distinct from a conversation ID. A chat can use one to track goals, progress and tool work.

The model API receives model-visible context and tool results. The Controller executes authorized tools; the model does not directly connect to a Worker or get your model API key. The browser presents the conversation and controls the Controller.

## Choose a guide

| I want to… | Read |
|---|---|
| Install, sign in and run a first task | [Quickstart](../getting-started/web-workspace.md) |
| Connect a model API or account | [Channels and models](channels.md) |
| Build reusable agents and delegate work | [Agents and Skills](agents.md) |
| Manage chats, files and projects | [Conversations](conversations.md) |
| Understand history retrieval and context budgets | [Memory and context](context.md) |
| Restrict execution and manage MCP tools | [Tools and permissions](permissions.md) |
| Run long tasks and schedules | [Goals and automation](automation.md) |
| Search the web and read documents | [Network search](../guides/webui-network-search.md) |
| Operate, back up and debug a deployment | [Administration and troubleshooting](administration.md) |

## First principles

Start with a narrowly scoped, read-only request on a known machine. Check the tool output before allowing modifications. A model can be incorrect even when a tool succeeds. Model credentials, chat storage, machine access and tool approvals are separate concerns; changing one does not automatically grant another. In particular, a public chat endpoint should be protected as a remote execution control plane.

For the external MCP client path, see [client connectivity](../clients/connectivity.md). For the underlying tool arguments, see [Tools reference](../reference/tools.md).
