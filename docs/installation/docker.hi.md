<!-- i18n-source-sha256: e2dd23efea9768d971fa8a8be723f55cfcac3279adfc82e4185a803e3f05de1e -->
# Docker Compose runtime

Docker Compose अधिकांश उपयोगकर्ताओं के लिए अनुशंसित runtime है। यह model को controlled Linux workspace, reproducible toolchain, persistent credentials, browser automation support और आसान upgrade path देता है।

यह runtime choice है। इसे ChatGPT, generic HTTP MCP client से जोड़ा जा सकता है या local testing के लिए रखा जा सकता है।

## Docker image में क्या शामिल है

Image Playwright Python image पर आधारित है और व्यापक development toolchain install करती है। उद्देश्य है कि AI coding agent हर project के लिए runtime rebuild किए बिना कई repositories पर काम कर सके।

शामिल categories:

| Category | Examples |
|---|---|
| Shell और inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git और credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| अन्य languages | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Document tooling | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

Image का exact content convenience layer है, stable API नहीं। Project-specific dependencies workspace या project build scripts में ही रहनी चाहिए।

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

बनाया गया local token host-owned `.env` (mode `0600`) में रहता है और Compose उसे container में पास करता है। इससे host पर `lsm call` container-owned state पढ़े बिना loopback controller से authenticate कर सकता है।

Default Compose file service को localhost से bind करती है:

```text
127.0.0.1:8765 -> container:8765
```

यह local testing और उसी host पर चलने वाले reverse proxy के लिए उपयुक्त है।

## Workspace layout

Default Compose runtime यह mount करता है:

| Host path या volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default` | `/workspace` | Tools को दिखने वाला controlled workspace |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistent Git/GitHub/SSH/GPG-style credential state |

हर trust boundary के लिए अलग workspace directory रखें। सुविधा के लिए पूरी home directory mount न करें।

## Required public settings

ChatGPT या public HTTP MCP client के लिए `.env` configure करें:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

JWT secret ऐसे command से generate करें:

```bash
openssl rand -hex 32
```

Public MCP URL है:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Compose file में `tunnel` profile के पीछे optional `cloudflared` service शामिल है। यह MCP server के साथ tunnel चलाती है।

`.env` configure करें:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

दोनों services शुरू करें:

```bash
docker compose --profile tunnel up -d
```

Cloudflare Zero Trust में public hostname को यहाँ route करें:

```text
http://local-shell-mcp:8765
```

यह Cloudflare Tunnel है, Cloudflare Access नहीं। ChatGPT के लिए OAuth `local-shell-mcp` स्वयं संभालता है।
Compose service forwarded headers पर trust करती है क्योंकि published port localhost तक सीमित है; इससे OAuth PIN rate limiting के लिए public caller address सुरक्षित रहता है। यदि container port सीधे expose करें, तो `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` को trusted reverse proxies के explicit addresses से बदलें।

## Tunnel sidecar के बिना reverse proxy

यदि Caddy, Nginx, Traefik या Nginx Proxy Manager पहले से चलता है, normal Compose service रखें और HTTPS यहाँ forward करें:

```text
http://127.0.0.1:8765
```

Proxy को path हटाए बिना ये routes forward करनी चाहिए:

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

Proxy behavior requirements के लिए [network connectivity](../clients/connectivity.md) देखें।

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` filesystem operations को workspace तक सीमित रखता है। यह अधिक सुरक्षित default है।

केवल तब `true` करें जब container जानबूझकर disposable हो और model को पूरा container filesystem operate करना हो। Enabled होने पर built-in command/path denylist restrictions हट जाती हैं।

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Laptop पर सीधे चल रहे VS Code extension या binary जैसे host-launched runtime में full-container mode enable न करें।

## Credentials

Docker runtime common developer credentials को dedicated volume में persist कर सकता है। GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config और GPG state के लिए उपयोगी है।

Credential volume को sensitive मानें। Repository-scoped deploy keys, fine-grained tokens या short-lived credentials को प्राथमिकता दें। Model द्वारा freely readable workspace में broad personal credentials न रखें।

SSH agent socket mount करके SSH-agent forwarding संभव है, लेकिन इससे container का trust active agent तक बढ़ता है। Exposure समझने पर ही उपयोग करें।

## Updates

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Tunnel sidecar के साथ:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Upgrade के बाद client से पहले read-only check कराएँ:

```text
local-shell-mcp उपयोग करें। environment_get कॉल करें और workspace root पर file_list चलाएँ। Files न बदलें।
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `/healthz` local में fail | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT tools discover नहीं करता | Public URL `/mcp` पर समाप्त हो; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` में `/mcp` न हो |
| OAuth page fail | Public OAuth deployments में admin PIN और JWT secret set हों |
| Tools files नहीं देख पाते | Intended host directory `/workspace` पर mounted है या नहीं जाँचें |
| Browser tools fail | Playwright image current हो; target browser के लिए `run_shell` आज़माएँ |
| Git auth गायब | Credential volume और recreated container में वही volume उपयोग जाँचें |
