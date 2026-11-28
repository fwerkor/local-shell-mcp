# WebUI Chat quickstart

The unified LSM web workspace integrates AI chat, projects, Agents and the Controller's operational pages. It is served by the Python Controller and uses its authentication and SQLite database. No separate chat server is needed. External MCP clients such as [ChatGPT](chatgpt-connector.md) and [Gemini](gemini-spark.md) remain supported.

## 1. Start the Controller

Follow the [installation quickstart](quickstart.md) for your preferred runtime. Ensure the WebUI is enabled and use persistent storage. The following are the normal defaults:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

After exporting your service environment, start the Controller:

```sh
local-shell-mcp --mode mcp
```

For the single-file release use the downloaded executable instead. The installed Controller serves the compiled frontend; the JavaScript build toolchain is only needed for source builds. See [WebUI build instructions](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## 2. Open the browser workspace

Open `http://127.0.0.1:8765/ui` from the Controller host, or the configured HTTPS URL ending in `/ui`. Sign in with the LSM authentication configured for that deployment. Use authenticated HTTPS for remote access. The chat and control pages share the same origin.

## 3. Add a model channel

Open the model selector and channel management. Add an API channel or connect a supported account. For a typical OpenAI-compatible endpoint enter a channel name, choose Chat Completions, enter the API base URL and credential, and discover models or supply a known model ID manually. Save the configuration and select a model.

For a local inference service, use an address reachable from the Controller, not just your browser. For example, `http://127.0.0.1:8080/v1` is appropriate if the inference service listens on that address inside the Controller's network namespace. See [Channels and models](../chat/channels.md) for protocols, account authorization, model discovery and context limits.

## 4. Run a first task

Start a chat and ask a simple question to test model connectivity. Then try a read-only tool request:

```text
List the files in the Controller workspace root.
Tell me which machine you inspected and summarize the result.
Do not modify files or run any writes.
```

Inspect the actual tool result. If a tool is missing, check the chat's tool toggles, Agent settings and machine permissions. Use a saved Agent for recurring tasks and configure its access explicitly. See [Tools and permissions](../chat/permissions.md).

![WebUI Chat with a demonstration conversation](../assets/chat/chat-workspace.png)

The screenshots in this guide and the following pages were captured in an isolated Controller with a demonstration model. They contain no production credentials or conversations. The English UI labels may differ from the selected language.

## 5. Explore the workspace

| Area | What to use it for |
|---|---|
| Chat and projects | Start and search chats, organize projects, tags and message bookmarks |
| Agents | Reusable model, instruction and tool configurations |
| Memory and Skills | Manage reusable knowledge and instructions |
| Scheduled chats | Run a saved Agent with a recurring prompt |
| Files and terminals | Inspect or operate on Controller and Worker environments |
| Desktop | Inspect and control supported remote GUI sessions |
| Sessions, jobs and audit | Inspect durable tasks, execution progress and tool activity |
| Machines and external MCP | Manage Workers and nested MCP servers |

The exact set of controls depends on your deployment, account and enabled capabilities. Closing the browser does not by itself cancel a server-side generation; use the stop control when you need to interrupt work.

## Next steps

Read the [WebUI Chat guide](../chat/index.md) for the complete workflow, and [Administration and troubleshooting](../chat/administration.md) for production setup, backup and error recovery.
