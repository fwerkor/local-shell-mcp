<!-- i18n-source-sha256: 931645b26427f12938872e36f9c9c3c5b45ff4697c5e3db8ae51d73bb10dc84c -->
# Runtime Docker Compose

Docker Compose è il runtime consigliato per la maggior parte degli utenti. Offre al modello un workspace Linux controllato, un toolchain riproducibile, credenziali persistenti, supporto browser automation e un percorso di upgrade semplice.

È una scelta di runtime. Può essere collegato a ChatGPT, a un MCP client HTTP generico oppure restare locale per i test.

## Cosa include l’immagine Docker

L’immagine si basa sull’immagine Python di Playwright e installa un ampio toolchain di sviluppo. L’obiettivo è permettere a un AI coding agent di lavorare su molti repository senza ricostruire il runtime per ogni progetto.

Categorie incluse:

| Categoria | Esempi |
|---|---|
| Shell e ispezione | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git e credenziali | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| Altri linguaggi | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Strumenti documentali | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

Il contenuto esatto dell’immagine è una convenience layer, non una API stabile. Le dipendenze specifiche del progetto devono restare nel workspace o nei build script del progetto.

## Esecuzione locale di base

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

Il token CLI grezzo rimane solo nel `.env` di proprietà dell’host (modalità `0600`). Compose passa al container soltanto il relativo verificatore SHA-256. In questo modo `lsm call` può autenticarsi attraverso il bridge della porta pubblicata da Docker senza esporre un token privilegiato riutilizzabile ai processi shell gestiti nel container.

Il Compose file predefinito collega il servizio a localhost:

```text
127.0.0.1:8765 -> container:8765
```

È adatto ai test locali e a un reverse proxy sullo stesso host.

## Layout del workspace

Il runtime Compose predefinito monta:

| Path o volume host | Path container | Scopo |
|---|---|---|
| `./workspaces/default` | `/workspace` | Workspace controllato visibile ai tool |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Stato persistente credenziali Git/GitHub/SSH/GPG |

Usa un workspace directory per ogni trust boundary. Non montare tutta la home directory solo per comodità.

## Impostazioni pubbliche richieste

Per ChatGPT o un MCP client HTTP pubblico, configura `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Genera un JWT secret con un comando come:

```bash
openssl rand -hex 32
```

L’URL MCP pubblico è:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Il Compose file include un servizio `cloudflared` opzionale dietro il profile `tunnel`. Esegue il tunnel accanto al MCP server.

Configura `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Avvia entrambi i servizi:

```bash
docker compose --profile tunnel up -d
```

In Cloudflare Zero Trust, instrada il public hostname a:

```text
http://local-shell-mcp:8765
```

Questo è Cloudflare Tunnel, non Cloudflare Access. `local-shell-mcp` continua a gestire il proprio OAuth per ChatGPT.
Il servizio Compose considera affidabili i forwarded headers perché la porta pubblicata è limitata a localhost; così conserva l’indirizzo pubblico del caller per il rate limiting dell’OAuth PIN. Se esponi direttamente la porta del container, sostituisci `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` con gli indirizzi espliciti dei reverse proxy fidati.

## Reverse proxy senza tunnel sidecar

Se usi già Caddy, Nginx, Traefik o Nginx Proxy Manager, mantieni il normale servizio Compose e inoltra HTTPS a:

```text
http://127.0.0.1:8765
```

Il proxy deve inoltrare queste route senza rimuovere i path:

| Route | Scopo |
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

Vedi [network connectivity](../clients/connectivity.md) per i requisiti del proxy.

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` limita le filesystem operations al workspace. È il default più sicuro.

Imposta `true` solo quando il container è intenzionalmente disposable e il modello deve operare l’intero filesystem del container. L’attivazione rimuove le restrizioni built-in command/path denylist.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Non abilitare full-container mode su un runtime avviato direttamente sull’host, come VS Code extension o un binary sul laptop.

## Credenziali

Il runtime Docker può persistere le credenziali comuni di sviluppo in un volume dedicato. È utile per GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config e stato GPG.

Tratta il volume delle credenziali come sensibile. Preferisci deploy key per repository, token fine-grained o credenziali di breve durata. Non mettere credenziali personali ampie in un workspace leggibile liberamente dal modello.

SSH-agent forwarding è possibile montando il socket dell’agente, ma estende la fiducia dal container al tuo agente attivo. Usalo solo se comprendi l’esposizione.

## Aggiornamenti

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Con tunnel sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Dopo l’upgrade, chiedi prima al client un check read-only:

```text
Usa local-shell-mcp. Chiama environment_get ed esegui file_list sulla radice del workspace. Non modificare file.
```

## Risoluzione dei problemi

| Sintomo | Controllo |
|---|---|
| `/healthz` fallisce localmente | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT non scopre i tool | La URL pubblica deve terminare con `/mcp`; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` non deve contenere `/mcp` |
| La pagina OAuth fallisce | Admin PIN e JWT secret devono essere impostati nei deployment OAuth pubblici |
| I tool non vedono i file | Conferma che la directory host prevista sia montata su `/workspace` |
| I browser tool falliscono | Conferma che l’immagine Playwright sia aggiornata; prova `run_shell` per il browser target |
| Git auth è scomparso | Controlla il volume credenziali e che il container ricreato usi lo stesso volume |
