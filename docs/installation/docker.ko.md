<!-- i18n-source-sha256: e2dd23efea9768d971fa8a8be723f55cfcac3279adfc82e4185a803e3f05de1e -->
# Docker Compose runtime

Docker Compose는 대부분의 사용자에게 권장되는 runtime입니다. 모델에 제어된 Linux workspace, 재현 가능한 toolchain, persistent credentials, browser automation support, 쉬운 upgrade path를 제공합니다.

이는 runtime 선택입니다. ChatGPT, generic HTTP MCP client에 연결하거나 local testing에만 사용할 수 있습니다.

## Docker image 포함 항목

Image는 Playwright Python image를 기반으로 하며 폭넓은 development toolchain을 설치합니다. AI coding agent가 project마다 runtime을 다시 build하지 않고 다양한 repository를 다루도록 하는 것이 목적입니다.

포함 category:

| Category | 예 |
|---|---|
| Shell 및 inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git 및 credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| 기타 언어 | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Document tooling | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

정확한 image content는 convenience layer이지 stable API가 아닙니다. Project-specific dependencies는 workspace나 project build scripts에 두어야 합니다.

## 기본 local run

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

생성된 로컬 token은 호스트 소유 `.env`(모드 `0600`)에 저장되고 Compose를 통해 컨테이너에 전달됩니다. 따라서 호스트의 `lsm call`은 컨테이너 소유 상태 파일을 읽지 않고 loopback controller에 인증할 수 있습니다.

Default Compose file은 service를 localhost에 bind합니다:

```text
127.0.0.1:8765 -> container:8765
```

이는 local testing과 같은 host에서 실행되는 reverse proxy에 적합합니다.

## Workspace layout

Default Compose runtime은 다음을 mount합니다:

| Host path / volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default` | `/workspace` | Tools에 노출되는 controlled workspace |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistent Git/GitHub/SSH/GPG-style credential state |

Trust boundary마다 하나의 workspace directory를 사용하십시오. 편의를 위해 home directory 전체를 mount하지 마십시오.

## 필수 public settings

ChatGPT 또는 public HTTP MCP client용 `.env`를 설정합니다:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

JWT secret은 다음과 같은 command로 만들 수 있습니다:

```bash
openssl rand -hex 32
```

Public MCP URL:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Compose file에는 `tunnel` profile 뒤의 optional `cloudflared` service가 포함되어 있습니다. Tunnel을 MCP server와 함께 실행합니다.

`.env`를 설정합니다:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

두 service를 시작합니다:

```bash
docker compose --profile tunnel up -d
```

Cloudflare Zero Trust에서 public hostname을 다음으로 route합니다:

```text
http://local-shell-mcp:8765
```

이는 Cloudflare Tunnel이며 Cloudflare Access가 아닙니다. ChatGPT용 OAuth는 계속 `local-shell-mcp`가 처리합니다.
Published port가 localhost로 제한되므로 Compose service는 forwarded headers를 신뢰합니다. 이를 통해 OAuth PIN rate limiting에 public caller address를 유지합니다. Container port를 직접 공개한다면 `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*`를 trusted reverse proxies의 명시적 address로 바꾸십시오.

## Tunnel sidecar 없는 reverse proxy

이미 Caddy, Nginx, Traefik 또는 Nginx Proxy Manager를 사용한다면 일반 Compose service를 유지하고 HTTPS를 다음으로 forward합니다:

```text
http://127.0.0.1:8765
```

Proxy는 path를 제거하지 않고 다음 routes를 forward해야 합니다:

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

Proxy behavior 요구 사항은 [network connectivity](../clients/connectivity.md)를 참조하십시오.

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false`는 filesystem operation을 workspace에 제한합니다. 더 안전한 default입니다.

Container가 의도적으로 disposable이고 model이 container filesystem 전체를 조작해야 할 때만 `true`로 설정하십시오. 활성화하면 built-in command/path denylist restrictions가 제거됩니다.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Laptop에서 직접 실행되는 VS Code extension 또는 binary 같은 host-launched runtime에서는 full-container mode를 활성화하지 마십시오.

## Credentials

Docker runtime은 일반적인 developer credentials를 dedicated volume에 영속화할 수 있습니다. GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config, GPG state에 유용합니다.

Credential volume은 sensitive하게 취급하십시오. Repository-scoped deploy key, fine-grained token, short-lived credential을 선호하고 model이 자유롭게 읽을 수 있는 workspace에 broad personal credential을 두지 마십시오.

SSH agent socket을 mount해 SSH-agent forwarding도 가능하지만 container가 active agent를 신뢰하게 됩니다. Exposure를 이해할 때만 사용하십시오.

## 업데이트

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Tunnel sidecar 사용 시:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Upgrade 후 client에 먼저 read-only check를 요청합니다:

```text
local-shell-mcp를 사용하세요. environment_get를 호출하고 workspace root에 file_list를 실행하세요. 파일은 수정하지 마세요.
```

## 문제 해결

| 증상 | 확인 |
|---|---|
| `/healthz` 가 local에서 실패 | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT가 tools를 discover하지 못함 | Public URL은 `/mcp`로 끝나야 하고 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`에는 `/mcp`를 넣지 않음 |
| OAuth page 실패 | Public OAuth deployment에서 admin PIN과 JWT secret 설정 |
| Tools에서 files가 보이지 않음 | 의도한 host directory가 `/workspace`에 mount되었는지 확인 |
| Browser tools 실패 | Playwright image가 current인지 확인하고 target browser에 `run_shell` 사용 |
| Git auth가 사라짐 | Credential volume과 재생성 container가 같은 volume을 사용하는지 확인 |
