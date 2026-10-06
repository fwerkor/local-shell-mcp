<!-- i18n-source-sha256: 931645b26427f12938872e36f9c9c3c5b45ff4697c5e3db8ae51d73bb10dc84c -->
# Runtime Docker Compose

Docker Compose to runtime zalecany większości użytkowników. Daje modelowi kontrolowany Linux workspace, reproducible toolchain, persistent credentials, browser automation support i łatwą ścieżkę upgrade.

To wybór runtime. Można go połączyć z ChatGPT, generic HTTP MCP client albo zachować lokalnie do testing.

## Co zawiera Docker image

Image opiera się na Playwright Python image i instaluje szeroki development toolchain. Celem jest umożliwienie AI coding agent pracy z wieloma repositories bez rebuild runtime dla każdego project.

Dostępne category:

| Category | Przykłady |
|---|---|
| Shell i inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git i credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| Inne języki | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Document tooling | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

Exact image content jest convenience layer, a nie stable API. Project-specific dependencies nadal należą do workspace lub project build scripts.

## Basic local run

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import hashlib,secrets; p=Path(".env"); s=p.read_text(); t=secrets.token_urlsafe(48); s=s.replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=" + t, 1).replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=" + hashlib.sha256(t.encode()).hexdigest(), 1); p.write_text(s)'
chmod 600 .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Surowy token CLI pozostaje wyłącznie w należącym do hosta pliku `.env` (tryb `0600`). Compose przekazuje do kontenera jedynie jego weryfikator SHA-256. Dzięki temu `lsm call` może uwierzytelnić się przez most opublikowanego portu Dockera bez ujawniania zarządzanym procesom shell w kontenerze wielokrotnego użytku uprzywilejowanego tokenu.

Default Compose file binduje service do localhost:

```text
127.0.0.1:8765 -> container:8765
```

Nadaje się to do local testing i reverse proxy działającego na tym samym host.

## Workspace layout

Default Compose runtime mountuje:

| Host path lub volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default` | `/workspace` | Controlled workspace widoczny dla tools |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistent Git/GitHub/SSH/GPG-style credential state |

Używaj jednego workspace directory na trust boundary. Nie mountuj całego home directory wyłącznie dla wygody.

## Required public settings

Dla ChatGPT lub public HTTP MCP client skonfiguruj `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Generate JWT secret poleceniem takim jak:

```bash
openssl rand -hex 32
```

Public MCP URL:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Compose file zawiera optional `cloudflared` service za profile `tunnel`. Uruchamia tunnel obok MCP server.

Skonfiguruj `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Uruchom oba service:

```bash
docker compose --profile tunnel up -d
```

W Cloudflare Zero Trust route public hostname do:

```text
http://local-shell-mcp:8765
```

To Cloudflare Tunnel, nie Cloudflare Access. `local-shell-mcp` nadal sam obsługuje OAuth dla ChatGPT.
Compose service ufa forwarded headers, ponieważ published port jest ograniczony do localhost; zachowuje to public caller address dla OAuth PIN rate limiting. Jeśli expose container port bezpośrednio, zastąp `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` jawnymi adresami trusted reverse proxies.

## Reverse proxy bez tunnel sidecar

Jeśli używasz już Caddy, Nginx, Traefik lub Nginx Proxy Manager, zachowaj normal Compose service i forward HTTPS do:

```text
http://127.0.0.1:8765
```

Proxy musi forwardować te routes bez usuwania path:

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

Wymagania proxy behavior opisuje [network connectivity](../clients/connectivity.md).

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` ogranicza filesystem operations do workspace. To bezpieczniejszy default.

Ustaw `true` tylko wtedy, gdy container jest celowo disposable i model ma operować całym container filesystem. Po włączeniu built-in command/path denylist restrictions są usuwane.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Nie włączaj full-container mode w host-launched runtime, takim jak VS Code extension lub binary działający bezpośrednio na laptopie.

## Credentials

Docker runtime może persist common developer credentials w dedicated volume. Jest to przydatne dla GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config i GPG state.

Traktuj credential volume jako sensitive. Preferuj repository-scoped deploy keys, fine-grained tokens lub short-lived credentials. Nie umieszczaj broad personal credentials w workspace, który model może swobodnie czytać.

SSH-agent forwarding jest możliwy przez mount socketu agenta, ale rozszerza trust z container na active agent. Używaj tylko jeśli rozumiesz exposure.

## Aktualizacje

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Z tunnel sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Po upgrade poproś client najpierw o read-only check:

```text
Użyj local-shell-mcp. Wywołaj environment_get i uruchom file_list na root workspace. Nie modyfikuj plików.
```

## Troubleshooting

| Objaw | Sprawdź |
|---|---|
| `/healthz` nie działa local | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT nie discoveruje tools | Public URL musi kończyć się `/mcp`; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` nie może zawierać `/mcp` |
| OAuth page nie działa | Admin PIN i JWT secret muszą być ustawione dla public OAuth deployments |
| Tools nie widzą files | Potwierdź, że intended host directory jest mounted do `/workspace` |
| Browser tools nie działają | Sprawdź, czy Playwright image jest current; spróbuj `run_shell` dla target browser |
| Git auth zniknął | Sprawdź credential volume i czy recreated container używa tego samego volume |
