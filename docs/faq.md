# Frequently asked questions

This page collects recurring client and reverse-proxy issues that can look like LSM failures even when the server itself is healthy.

## Why are some ChatGPT tools unavailable after upgrading LSM?

### Symptoms

- New tools are missing in ChatGPT.
- ChatGPT still tries to call a tool that was removed, renamed, or merged.
- A tool exists, but calls fail because ChatGPT sends an older input schema.
- Restarting LSM or opening a new conversation does not fix the problem.

### Cause

ChatGPT can keep a frozen snapshot of the tools and input schemas that were available when an MCP App was scanned, approved, or published. When an LSM release changes `tools/list`, that stored snapshot is not guaranteed to refresh automatically. This is not a short-lived cache with a documented expiration time.

### Resolution

=== "Developer mode or a personal connection"

    1. Open **ChatGPT Settings → Apps**.
    2. Open the LSM App and use **Refresh** to scan its tools again.
    3. If Refresh is unavailable, delete the old App and add the same MCP endpoint again.
    4. Start a new conversation after the updated tool list has been accepted.

=== "ChatGPT Business published App"

    A published custom App cannot currently update its tools or metadata in place. A workspace administrator must create a new App, scan the current LSM endpoint, publish the replacement, and retire the old App.

=== "ChatGPT Enterprise or Edu"

    A workspace administrator can open **Workspace Settings → Apps → the LSM App → … → Action control → Refresh**, review the differences, and enable newly discovered actions when necessary.

See [issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) and the [OpenAI MCP App documentation](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## Why does the WebUI keep reconnecting when LSM is behind Nginx?

### Symptoms

- The WebUI page and OAuth login load normally.
- The TUI never appears.
- The connection state repeatedly changes between `Connecting`, `Connection error`, and `Reconnecting`.
- Connecting directly to port `8765` works.

### Cause

The browser UI renders the native TUI through a PTY WebSocket. Its default endpoint is `/ui/ws`; with a custom `ui_path`, it is `${ui_path}/ws`. A normal Nginx `proxy_pass` does not automatically forward the hop-by-hop headers required for a WebSocket upgrade.

### Resolution

Enable HTTP/1.1 and forward the `Upgrade` and `Connection` headers:

```nginx
# Put this map in the http block.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

After editing the configuration, validate and reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

For Nginx Proxy Manager, enable **Websockets Support** on the Proxy Host. If the UI still reconnects, add the equivalent upgrade headers in the Advanced configuration.

### Verification

Open the browser developer tools, reload the WebUI, and inspect the `/ui/ws` request. A working connection returns:

```text
101 Switching Protocols
```

See [issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
