<!-- i18n-source-sha256: 931645b26427f12938872e36f9c9c3c5b45ff4697c5e3db8ae51d73bb10dc84c -->
# Runtime Docker Compose

Docker Compose adalah runtime yang direkomendasikan untuk sebagian besar pengguna. Ia memberi model workspace Linux terkontrol, toolchain reproducible, persistent credentials, dukungan browser automation, dan jalur upgrade yang mudah.

Ini adalah pilihan runtime. Dapat dihubungkan ke ChatGPT, generic HTTP MCP client, atau tetap lokal untuk testing.

## Isi Docker image

Image berbasis Playwright Python image dan memasang development toolchain yang luas. Tujuannya agar AI coding agent dapat menangani banyak repository tanpa meminta rebuild runtime untuk setiap project.

Category yang termasuk:

| Category | Contoh |
|---|---|
| Shell dan inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git dan credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| Bahasa lain | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Document tooling | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

Exact image content adalah convenience layer, bukan stable API. Project-specific dependencies tetap harus berada di workspace atau project build scripts.

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

Token CLI mentah hanya berada di `.env` milik host (mode `0600`). Compose hanya meneruskan verifier SHA-256 ke container. Dengan demikian `lsm call` dapat melakukan autentikasi melalui bridge port Docker yang dipublikasikan tanpa mengekspos token berhak tinggi yang dapat digunakan ulang kepada proses shell terkelola di dalam container.

Default Compose file mengikat service ke localhost:

```text
127.0.0.1:8765 -> container:8765
```

Ini sesuai untuk local testing dan reverse proxy yang berjalan pada host yang sama.

## Workspace layout

Default Compose runtime melakukan mount:

| Host path atau volume | Container path | Purpose |
|---|---|---|
| `./workspaces/default` | `/workspace` | Controlled workspace yang terlihat oleh tools |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistent Git/GitHub/SSH/GPG-style credential state |

Gunakan satu workspace directory per trust boundary. Jangan mount seluruh home directory hanya demi kenyamanan.

## Required public settings

Untuk ChatGPT atau public HTTP MCP client lain, konfigurasikan `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Generate JWT secret dengan command seperti:

```bash
openssl rand -hex 32
```

Public MCP URL:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Compose file menyertakan optional `cloudflared` service di balik profile `tunnel`. Ini menjalankan tunnel di samping MCP server.

Konfigurasikan `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Mulai kedua service:

```bash
docker compose --profile tunnel up -d
```

Di Cloudflare Zero Trust, route public hostname ke:

```text
http://local-shell-mcp:8765
```

Ini Cloudflare Tunnel, bukan Cloudflare Access. `local-shell-mcp` tetap menangani OAuth sendiri untuk ChatGPT.
Compose service mempercayai forwarded headers karena published port dibatasi ke localhost; ini mempertahankan public caller address untuk OAuth PIN rate limiting. Jika container port diekspos langsung, ganti `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` dengan alamat eksplisit trusted reverse proxies.

## Reverse proxy tanpa tunnel sidecar

Jika sudah memakai Caddy, Nginx, Traefik, atau Nginx Proxy Manager, pertahankan normal Compose service dan forward HTTPS ke:

```text
http://127.0.0.1:8765
```

Proxy harus forward routes berikut tanpa menghapus path:

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

Lihat [network connectivity](../clients/connectivity.md) untuk kebutuhan perilaku proxy.

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` membatasi filesystem operations ke workspace. Ini default yang lebih aman.

Set `true` hanya ketika container sengaja disposable dan model diharapkan mengoperasikan seluruh container filesystem. Saat aktif, built-in command/path denylist restrictions dihapus.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Jangan aktifkan full-container mode pada host-launched runtime seperti VS Code extension atau binary yang berjalan langsung di laptop.

## Credentials

Docker runtime dapat menyimpan common developer credentials dalam dedicated volume. Berguna untuk GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config, dan GPG state.

Perlakukan credential volume sebagai sensitive. Utamakan repository-scoped deploy keys, fine-grained tokens, atau short-lived credentials. Jangan letakkan broad personal credentials dalam workspace yang dapat dibaca bebas oleh model.

SSH-agent forwarding dimungkinkan dengan mount SSH agent socket, tetapi memperluas trust dari container ke active agent. Gunakan hanya jika memahami exposure.

## Pembaruan

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Dengan tunnel sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Setelah upgrade, minta client menjalankan read-only check terlebih dahulu:

```text
Gunakan local-shell-mcp. Panggil environment_get dan jalankan file_list pada root workspace. Jangan ubah file.
```

## Troubleshooting

| Gejala | Periksa |
|---|---|
| `/healthz` gagal secara lokal | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT tidak discover tools | Public URL harus berakhir `/mcp`; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` tidak boleh memuat `/mcp` |
| OAuth page gagal | Admin PIN dan JWT secret harus ditetapkan untuk public OAuth deployments |
| Tools tidak melihat file | Pastikan host directory yang dimaksud mounted ke `/workspace` |
| Browser tools gagal | Pastikan Playwright image current; coba `run_shell` untuk target browser |
| Git auth hilang | Periksa credential volume dan apakah recreated container memakai volume yang sama |
