# 常见问题

本页汇总一些反复出现的 Client 与反向代理问题。这些问题看起来像 LSM 服务故障，但服务端本身通常是正常的。

## 为什么升级 LSM 后，ChatGPT 中有些工具不可用？

### 表现

- ChatGPT 中看不到新增工具。
- ChatGPT 仍尝试调用已经删除、重命名或合并的旧工具。
- 工具仍存在，但 ChatGPT 使用旧参数结构，导致调用校验失败。
- 重启 LSM 或新建对话后问题仍然存在。

### 原因

ChatGPT 可能会保存 MCP App 在扫描、批准或发布时的工具及输入参数冻结快照。LSM 新版本修改 `tools/list` 后，这份已保存的快照并不保证自动刷新。这不是一个有明确过期时间的短期缓存。

### 解决方法

=== "开发者模式或个人连接"

    1. 打开 **ChatGPT 设置 → Apps**。
    2. 进入 LSM App，使用 **Refresh** 重新扫描工具。
    3. 如果没有 Refresh，删除旧 App，再用同一个 MCP 地址重新添加。
    4. 接受新工具列表后，新建一个对话再使用 LSM。

=== "ChatGPT Business 已发布 App"

    当前已发布的自定义 App 无法原地更新工具或元数据。工作区管理员需要新建 App，扫描当前 LSM 地址，发布替代版本，然后停用旧 App。

=== "ChatGPT Enterprise 或 Edu"

    工作区管理员可以进入 **Workspace Settings → Apps → LSM App → … → Action control → Refresh**，审核差异，并按需启用新发现的 action。

参见 [Issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) 和 [OpenAI MCP App 文档](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)。

## 为什么通过 Nginx 反代 LSM 后，WebUI 一直重连？

### 表现

- WebUI 页面和 OAuth 登录都能正常打开。
- TUI 始终不显示。
- 连接状态不断在 `Connecting`、`Connection error` 和 `Reconnecting` 之间变化。
- 直接连接 `8765` 端口时一切正常。

### 原因

浏览器界面通过 PTY WebSocket 渲染原生 TUI。默认端点是 `/ui/ws`；如果自定义了 `ui_path`，端点就是 `${ui_path}/ws`。普通的 Nginx `proxy_pass` 不会自动转发 WebSocket 协议升级所需的 hop-by-hop 请求头。

### 解决方法

启用 HTTP/1.1，并转发 `Upgrade` 和 `Connection` 请求头：

```nginx
# 将 map 放在 http 块中。
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

修改配置后，检查并重新加载 Nginx：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

如果使用 Nginx Proxy Manager，请在对应 Proxy Host 中启用 **Websockets Support**。如果仍然重连，在 Advanced 配置中补充等价的协议升级请求头。

### 验证

打开浏览器开发者工具，重新加载 WebUI，并检查 `/ui/ws` 请求。正常连接应返回：

```text
101 Switching Protocols
```

参见 [Issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71)。
