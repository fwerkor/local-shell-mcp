<!-- i18n-source-sha256: e2dd23efea9768d971fa8a8be723f55cfcac3279adfc82e4185a803e3f05de1e -->
# Runtime Docker Compose

Docker Compose là runtime khuyến nghị cho phần lớn người dùng. Nó cung cấp cho model workspace Linux được kiểm soát, toolchain tái lập, persistent credentials, hỗ trợ browser automation và đường upgrade dễ dàng.

Đây là lựa chọn runtime. Có thể kết nối với ChatGPT, generic HTTP MCP client hoặc giữ local để testing.

## Docker image bao gồm gì

Image dựa trên Playwright Python image và cài development toolchain rộng. Mục tiêu là để AI coding agent xử lý nhiều repository mà không cần rebuild runtime cho từng project.

Các category có sẵn:

| Category | Ví dụ |
|---|---|
| Shell và inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git và credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| Ngôn ngữ khác | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Document tooling | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

Exact image content là convenience layer, không phải stable API. Project-specific dependencies vẫn thuộc workspace hoặc project build scripts.

## Basic local run

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Token cục bộ được tạo nằm trong `.env` thuộc sở hữu host (mode `0600`) và được Compose truyền vào container. Nhờ đó, `lsm call` trên host có thể xác thực với loopback controller mà không cần đọc state thuộc sở hữu container.

Default Compose file bind service vào localhost:

```text
127.0.0.1:8765 -> container:8765
```

Phù hợp cho local testing và reverse proxy chạy trên cùng host.

## Workspace layout

Default Compose runtime mount:

| Host path hoặc volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default` | `/workspace` | Controlled workspace hiển thị cho tools |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistent Git/GitHub/SSH/GPG-style credential state |

Dùng một workspace directory cho mỗi trust boundary. Đừng mount toàn bộ home directory chỉ vì tiện.

## Required public settings

Cho ChatGPT hoặc public HTTP MCP client, cấu hình `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Generate JWT secret bằng command như:

```bash
openssl rand -hex 32
```

Public MCP URL:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Compose file có optional `cloudflared` service sau profile `tunnel`. Nó chạy tunnel cạnh MCP server.

Cấu hình `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Khởi động cả hai service:

```bash
docker compose --profile tunnel up -d
```

Trong Cloudflare Zero Trust, route public hostname tới:

```text
http://local-shell-mcp:8765
```

Đây là Cloudflare Tunnel, không phải Cloudflare Access. `local-shell-mcp` vẫn tự xử lý OAuth cho ChatGPT.
Compose service tin forwarded headers vì published port giới hạn ở localhost; nhờ đó giữ public caller address cho OAuth PIN rate limiting. Nếu expose container port trực tiếp, thay `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` bằng địa chỉ rõ ràng của trusted reverse proxies.

## Reverse proxy không có tunnel sidecar

Nếu đã dùng Caddy, Nginx, Traefik hoặc Nginx Proxy Manager, giữ normal Compose service và forward HTTPS tới:

```text
http://127.0.0.1:8765
```

Proxy phải forward các routes này mà không strip path:

| Route | Purpose |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/oauth-protected-resource` | OAuth resource metadata |
| `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata |
| `/oauth/register` | Dynamic client registration |
| `/oauth/authorize` | Browser authorization page |
| `/oauth/token` | Token exchange |
| `/downloads/<token>` | Optional generated file downloads |
| `/join/<token>`, `/remote/*` | Optional remote-worker bootstrap / polling |

Xem [network connectivity](../clients/connectivity.md) cho yêu cầu về proxy behavior.

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` giới hạn filesystem operations trong workspace. Đây là default an toàn hơn.

Chỉ set `true` khi container cố ý disposable và model cần operate toàn bộ container filesystem. Khi bật, built-in command/path denylist restrictions bị loại bỏ.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Không bật full-container mode trên host-launched runtime như VS Code extension hoặc binary chạy trực tiếp trên laptop.

## Credentials

Docker runtime có thể persist common developer credentials trong dedicated volume. Hữu ích cho GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config và GPG state.

Xem credential volume là sensitive. Ưu tiên repository-scoped deploy keys, fine-grained tokens hoặc short-lived credentials. Không đặt broad personal credentials trong workspace mà model đọc tự do.

Có thể SSH-agent forwarding bằng cách mount SSH agent socket, nhưng việc này mở rộng trust từ container tới active agent. Chỉ dùng khi hiểu exposure.

## Cập nhật

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Với tunnel sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Sau upgrade, trước tiên yêu cầu client chạy read-only check:

```text
Dùng local-shell-mcp. Gọi environment_get và chạy file_list trên root workspace. Không sửa file.
```

## Troubleshooting

| Triệu chứng | Kiểm tra |
|---|---|
| `/healthz` lỗi local | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT không discover tools | Public URL phải kết thúc `/mcp`; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` không được chứa `/mcp` |
| OAuth page lỗi | Admin PIN và JWT secret phải được set cho public OAuth deployments |
| Tools không thấy file | Xác nhận host directory dự kiến được mount tới `/workspace` |
| Browser tools lỗi | Xác nhận Playwright image current; thử `run_shell` cho target browser |
| Git auth biến mất | Kiểm tra credential volume và recreated container có dùng cùng volume không |
