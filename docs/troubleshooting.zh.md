# 故障排查

检查服务健康状态：

```bash
curl -i http://127.0.0.1:8765/healthz
```

检查日志：

```bash
docker compose logs --tail=100 local-shell-mcp
```

如果 ChatGPT 无法连接，确认 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 是准确的公开 HTTPS origin，并确认 `/mcp`、OAuth 元数据和 `/healthz` 可以通过隧道或反向代理访问。

如果远程 worker 没有出现，确认远程模式已启用、邀请尚未过期，并且远程机器可以向控制服务发起出站 HTTPS 请求。
