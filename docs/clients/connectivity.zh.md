<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# 网络连通性

机器外部的 HTTP MCP 客户端需要可访问的 HTTPS origin。本页讨论网络路由，不讨论选择哪种运行时。

客户端端点通常以 `/mcp` 结尾：

```text
https://your-public-host.example.com/mcp
```

服务端的 public base URL 设置只填写 origin：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

不要在这个 base URL 中包含 `/mcp`。

## 连通性选项

**推荐：** 有条件时应直接部署到具有公网地址的服务器，或通过公网服务器配合 HTTPS 反向代理转发流量。

**不推荐：** Cloudflare Tunnel 客户端的上传速度可能非常慢，导致文件上传与传输功能难以正常使用。仅在无法公网部署或通过公网服务器转发时，才将其作为备选方案。


| 选项 | 适用场景 |
|---|---|
| Caddy | 简单自动 TLS |
| Nginx 或 Nginx Proxy Manager | 已有 Nginx 基础设施 |
| Traefik | 已有容器原生路由 |
| 通过公网服务器转发 | 有条件时应直接部署到具有公网地址的服务器，或通过公网服务器配合 HTTPS 反向代理转发流量。 |
| Cloudflare Tunnel（不推荐） | 通过公网服务器转发；Cloudflare Tunnel 仅作备选 |

## 路径

把整个 origin 转发到正在运行的服务。重要路径包括：

| 路径 | 用途 |
|---|---|
| `/mcp` | MCP streamable HTTP 端点 |
| `/healthz`, `/readyz` | 健康检查 |
| `/.well-known/...` | 客户端发现元数据 |
| `/oauth/...` | 客户端授权流程 |
| `/downloads/...` | 可选的生成文件链接 |
| `/join/...`, `/remote/...` | 可选的远程 worker 流程 |

## 代理行为

代理应保留路径、转发请求体、支持长响应，并避免过短超时。

## 检查

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## 常见错误

| 错误 | 修正 |
|---|---|
| 在 ChatGPT 中使用 `https://host` 而不是 `https://host/mcp` | 只在客户端端点中添加 `/mcp` |
| 设置 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | 只设置 origin |
| 只路由 `/mcp` | 路由整个 origin，确保发现和授权路径也可用 |
| 在宿主机运行时中使用过宽工作区 | 使用较窄工作区或 Docker |

## 推荐搭配

| 运行时 | 网络模式 |
|---|---|
| 服务器上的 Docker Compose | HTTPS 反向代理 |
| 家用机器上的 Docker Compose | 通过公网服务器转发；Cloudflare Tunnel 仅作备选 |
| 笔记本上的 VS Code 扩展 | 通过公网服务器转发 |
| VM 上的二进制 | VM 或网络边缘上的反向代理 |
| Python / 源码开发服务 | 通常只用 localhost |
| stdio 模式 | 无 HTTP 网络路径；使用本地 MCP 客户端 |
