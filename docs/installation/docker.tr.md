<!-- i18n-source-sha256: e2dd23efea9768d971fa8a8be723f55cfcac3279adfc82e4185a803e3f05de1e -->
# Docker Compose runtime

Docker Compose çoğu kullanıcı için önerilen runtime’dır. Modele kontrollü Linux workspace, reproducible toolchain, persistent credentials, browser automation desteği ve kolay upgrade yolu sağlar.

Bu bir runtime seçimidir. ChatGPT’ye, generic HTTP MCP client’a bağlanabilir veya local testing için yerel tutulabilir.

## Docker image içeriği

Image, Playwright Python image tabanlıdır ve geniş development toolchain kurar. Amaç, AI coding agent’ın her project için runtime rebuild etmeden birçok repository üzerinde çalışabilmesidir.

Dahil category’ler:

| Category | Örnekler |
|---|---|
| Shell ve inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git ve credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| Diğer diller | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Document tooling | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

Exact image content bir convenience layer’dır, stable API değildir. Project-specific dependencies workspace veya project build scripts içinde kalmalıdır.

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

Üretilen yerel token, host tarafından sahip olunan `.env` dosyasında (mod `0600`) kalır ve Compose tarafından container’a aktarılır. Böylece host üzerindeki `lsm call`, container’a ait durum dosyalarını okumadan loopback controller’a kimlik doğrulayabilir.

Default Compose file service’i localhost’a bind eder:

```text
127.0.0.1:8765 -> container:8765
```

Bu local testing ve aynı host üzerinde çalışan reverse proxy için uygundur.

## Workspace layout

Default Compose runtime şunları mount eder:

| Host path veya volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default` | `/workspace` | Tools tarafından görülen controlled workspace |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistent Git/GitHub/SSH/GPG-style credential state |

Her trust boundary için bir workspace directory kullanın. Kolaylık için tüm home directory’yi mount etmeyin.

## Required public settings

ChatGPT veya public HTTP MCP client için `.env` yapılandırın:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

JWT secret’ı şu tür bir command ile generate edin:

```bash
openssl rand -hex 32
```

Public MCP URL:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Compose file `tunnel` profile arkasında optional `cloudflared` service içerir. Tunnel’ı MCP server yanında çalıştırır.

`.env` yapılandırın:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

İki service’i de başlatın:

```bash
docker compose --profile tunnel up -d
```

Cloudflare Zero Trust içinde public hostname’i şuraya route edin:

```text
http://local-shell-mcp:8765
```

Bu Cloudflare Tunnel’dır, Cloudflare Access değildir. ChatGPT OAuth işlemlerini yine `local-shell-mcp` yürütür.
Compose service, published port localhost ile sınırlı olduğundan forwarded headers’a güvenir; böylece OAuth PIN rate limiting için public caller address korunur. Container port’u doğrudan expose ederseniz `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` değerini trusted reverse proxies’in açık adresleriyle değiştirin.

## Tunnel sidecar olmadan reverse proxy

Caddy, Nginx, Traefik veya Nginx Proxy Manager zaten kullanıyorsanız normal Compose service’i koruyup HTTPS’i şuraya forward edin:

```text
http://127.0.0.1:8765
```

Proxy şu routes’u path strip etmeden forward etmelidir:

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

Proxy behavior gereksinimleri için [network connectivity](../clients/connectivity.md) bölümüne bakın.

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` filesystem operations’ı workspace ile sınırlar. Daha güvenli default budur.

Yalnız container bilerek disposable ise ve model tüm container filesystem üzerinde çalışacaksa `true` yapın. Etkinleşince built-in command/path denylist restrictions kaldırılır.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Laptop üzerinde doğrudan çalışan VS Code extension veya binary gibi host-launched runtime’da full-container mode’u etkinleştirmeyin.

## Credentials

Docker runtime common developer credentials’ı dedicated volume içinde persist edebilir. GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config ve GPG state için kullanışlıdır.

Credential volume’u sensitive kabul edin. Repository-scoped deploy keys, fine-grained tokens veya short-lived credentials tercih edin. Modelin freely readable workspace’ine broad personal credentials koymayın.

SSH agent socket mount ederek SSH-agent forwarding mümkündür ancak container’dan active agent’a trust’ı genişletir. Exposure’u anlıyorsanız kullanın.

## Güncellemeler

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Tunnel sidecar ile:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Upgrade sonrası client’tan önce read-only check isteyin:

```text
local-shell-mcp kullan. environment_get çağır ve workspace root üzerinde file_list çalıştır. Dosyaları değiştirme.
```

## Troubleshooting

| Belirti | Kontrol |
|---|---|
| `/healthz` local’de başarısız | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT tools discover edemiyor | Public URL `/mcp` ile bitmeli; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` içinde `/mcp` olmamalı |
| OAuth page başarısız | Public OAuth deployments için admin PIN ve JWT secret set edilmeli |
| Tools files göremiyor | Amaçlanan host directory’nin `/workspace` üzerine mount edildiğini doğrulayın |
| Browser tools başarısız | Playwright image current mı kontrol edin; target browser için `run_shell` deneyin |
| Git auth kayboldu | Credential volume ve recreated container’ın aynı volume’u kullandığını kontrol edin |
