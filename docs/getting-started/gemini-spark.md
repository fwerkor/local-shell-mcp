# Connect Gemini Spark / Custom Apps

Gemini's **custom connected apps** feature (previously described as **Spark**) lets an eligible Gemini user connect a remote MCP server. LSM can provide the MCP endpoint. This is an **alternative client connection** to the [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) and other MCP clients; it does not replace or deploy the LSM Controller.

Google currently restricts custom apps to **users aged 18 or older in the United States**, signed in with a **personal Google Account** and **Keep Activity enabled**. The feature is available in **English**. Connections must be created on the Gemini web app, although connected apps can later be used on mobile. Availability and UI labels may change; consult the [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

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
2. Open **Settings & help → Connected Apps**. Depending on the current interface, it may be under **Personal Intelligence → Connected Apps**.
3. Under **Custom apps**, select **Add a custom app** or use the custom-app URL field.
4. Paste the LSM HTTPS `/mcp` URL, then choose **Next**.
5. Complete the OAuth and consent flow with the LSM Controller. LSM supports OAuth discovery and dynamic client registration. If Gemini requests manual OAuth client credentials instead, check its advanced options and your LSM OAuth setup before proceeding.
6. In a Gemini conversation, type `@` and select the connected custom app to request an LSM tool.

Start with: “Use the connected LSM app to inspect the environment and list workspace files. Do not modify anything.” Check the tool results and Controller audit before attempting write operations.

## Limits and troubleshooting

- **No Custom apps option:** confirm account, region, age, language and Keep Activity eligibility. This is a Gemini-side availability restriction, not an LSM configuration error.
- **URL is rejected:** use an externally reachable HTTPS `/mcp` endpoint; check OAuth discovery and your reverse proxy.
- **OAuth fails:** check the LSM authorization screen, client registration, callback URL and granted scopes. Do not publish an unauthenticated MCP endpoint.
- **A tool is missing or fails:** client-side MCP tool/schema support can differ. Try a simple read-only call and inspect LSM audit and logs; full compatibility with every Gemini client feature is not guaranteed.
- **Disconnecting:** go back to **Connected Apps** to disable, unlink or remove LSM when it is no longer needed.

Google's [official guide](https://support.google.com/gemini/answer/17209137) describes the latest Custom Apps flow and availability. For a local CLI-based Gemini integration instead, see [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). The LSM [ChatGPT connector tutorial](chatgpt-connector.md) remains available independently.
