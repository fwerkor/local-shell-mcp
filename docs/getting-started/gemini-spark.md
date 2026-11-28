# Connect Gemini Task / Custom Apps

Gemini's **custom connected apps** feature lets an eligible Gemini user connect a remote MCP server. LSM can provide the MCP endpoint. This is an **alternative client connection** to the [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) and other MCP clients; it does not replace or deploy the LSM Controller.

Google currently restricts custom apps to **users aged 18 or older in the United States**, signed in with a **personal Google Account** and **History (formerly Keep Activity) enabled**. The feature is available in **English**. Connections must be created on the Gemini web app, although connected apps can later be used on mobile. Availability and UI labels may change; consult the [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

## Before connecting

- Start an LSM runtime, for example with [Docker Compose](../installation/docker.md), and verify its health.
- Expose its MCP endpoint over **publicly reachable HTTPS** and keep OAuth enabled.
- Know the Controller's authentication details and approve only scopes you need.
- Use a constrained workspace or container. Gemini may request operations with real effects on files, machines and terminals.

The endpoint to enter in Gemini is:

```text
https://your-public-host.example.com/mcp
```

Do not enter the web UI (`/ui`), the LibreChat URL or the site origin without `/mcp`. Public deployments should not disable authentication to work around connection errors.

## Connect in Gemini

1. On a computer, open [Gemini](https://gemini.google.com/) and sign in with an eligible personal account.
2. Open **Settings → Connected Apps**. Depending on the current interface, it may be under **Personal Intelligence → Connected Apps**.
3. Under **Custom apps**, select **Add a custom app** or use the custom-app URL field.
4. Paste the LSM HTTPS `/mcp` URL, then choose **Next**.
5. Complete the OAuth and consent flow with the LSM Controller. LSM supports OAuth discovery and dynamic client registration. If Gemini requests manual OAuth client credentials instead, check its advanced options and your LSM OAuth setup before proceeding.
6. In a Gemini conversation, type `@` and select the connected custom app to request an LSM tool.

Start with: “Use the connected LSM app to inspect the environment and list workspace files. Do not modify anything.” Check the tool results and Controller audit before attempting write operations.

## Use Task mode (formerly Spark)

For multi-step coding, debugging or server maintenance, prefer **Task** over ordinary chat: it can plan work, use connected tools repeatedly and expose progress in a task thread. This is a workflow recommendation, not a measured speed or quality guarantee.

On Gemini's home screen, select **Task** below the prompt box and complete onboarding if prompted. Type `@`, choose the LSM custom app if offered, and submit a concrete goal with the target machine/workspace and completion criteria.

Example: “Use LSM to inspect the repository, reproduce the failing test, fix the cause and rerun the tests. Report the changed files and test results.”

Monitor the task's progress and approve requested actions as appropriate. Verify actual LSM tool calls in the Controller audit: Gemini's own cloud computer is not your LSM workspace. Keep the Controller and any required workers online. Task availability is separate from Custom Apps eligibility; if either is missing, check the [official Task guide](https://support.google.com/gemini/answer/17094507).

## Limits and troubleshooting

- **No Custom apps option:** confirm account, region, age, language and History eligibility. This is a Gemini-side availability restriction, not an LSM configuration error.
- **URL is rejected:** use an externally reachable HTTPS `/mcp` endpoint; check OAuth discovery and your reverse proxy.
- **OAuth fails:** check the LSM authorization screen, client registration, callback URL and granted scopes. Do not publish an unauthenticated MCP endpoint.
- **A tool is missing or fails:** client-side MCP tool/schema support can differ. Try a simple read-only call and inspect LSM audit and logs; full compatibility with every Gemini client feature is not guaranteed.
- **Disconnecting:** go back to **Connected Apps** to disable, unlink or remove LSM when it is no longer needed.

Google's [official guide](https://support.google.com/gemini/answer/17209137) describes the latest Custom Apps flow and availability. For a local CLI-based Gemini integration instead, see [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). The LSM [ChatGPT connector tutorial](chatgpt-connector.md) remains available independently.
