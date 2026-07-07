# 故障排查

檢查服務健康狀態：

```bash
curl -i http://127.0.0.1:8765/healthz
```

檢查日誌：

```bash
docker compose logs --tail=100 local-shell-mcp
```

如果 ChatGPT 無法連接，確認 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 是準確的公開 HTTPS origin，並確認 `/mcp`、OAuth 元數據和 `/healthz` 可以通過隧道或反向代理訪問。

如果遠程 worker 沒有出現，確認遠程模式已啓用、邀請尚未過期，並且遠程機器可以向控制服務發起出站 HTTPS 請求。
