<!-- i18n-source-sha256: 81fe33aa286565e6436467d117cc77d94ec91671e33e559a6bb888223d0c8bc1 -->
# Avvio rapido

Questa guida usa Docker Compose come primo runtime e ChatGPT come primo client. Sono scelte indipendenti: Docker, VS Code extension, binary, Python e stdio sono opzioni di runtime; ChatGPT e i client MCP generici sono opzioni di client. Consulta [scelte del runtime e modello di deployment](../guides/deployment.md) per la mappa completa.

## Requisiti

- Docker Engine con Compose v2.
- Un endpoint HTTPS pubblico se ChatGPT deve collegarsi dal Web.
- Una directory workspace dedicata.
- Un OAuth admin PIN e JWT secret lunghi e casuali.

!!! warning
    Il modello connesso può operare il workspace configurato. Esegui il servizio in un container o VM usa e getta ed evita di montare risorse di controllo dell’host.

## 1. Clonare e configurare

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import hashlib,secrets; p=Path(".env"); s=p.read_text(); t=secrets.token_urlsafe(48); s=s.replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=" + t, 1).replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=" + hashlib.sha256(t.encode()).hexdigest(), 1); p.write_text(s)'
chmod 600 .env
```

Modifica `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. Avviare il server

```bash
mkdir -p workspaces/default
docker compose up -d
```

Controlla lo stato:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Una risposta sana restituisce HTTP `200`.

## 3. Esporre HTTPS

Per il sidecar Cloudflare Tunnel:

```bash
docker compose --profile tunnel up -d
```

In Cloudflare Zero Trust, punta il public hostname a:

```text
http://local-shell-mcp:8765
```

Con Caddy, Nginx, Traefik, Nginx Proxy Manager o un altro reverse proxy, inoltra il traffico HTTPS a `127.0.0.1:8765` o all’indirizzo di rete del container.

## 4. Connettere ChatGPT

Usa l’endpoint MCP:

```text
https://your-public-host.example.com/mcp
```

Segui la [guida del connettore ChatGPT](chatgpt-connector.md) per completare OAuth e approvazione degli strumenti.

## 5. Confermare in sicurezza l’accesso agli strumenti

Chiedi al modello:

```text
Usa local-shell-mcp. Prima chiama environment_get, poi elenca la radice del workspace. Non modificare ancora i file.
```

Strumenti read-only previsti:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Iniziare con un task di coding circoscritto

Un buon primo task:

```text
Ispeziona questo repository, riassumi il layout del progetto, esegui la suite di test esistente se è evidente e non modificare i file.
```

Dopo aver confermato la connettività, fornisci istruzioni più specifiche:

```text
Correggi il test che fallisce. Leggi prima i file pertinenti, applica la patch minima, esegui il test mirato e poi mostra git diff. Non fare commit finché non approvo.
```

## Aggiornamento

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Se usi il profilo tunnel:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

## Pagine successive

| Esigenza | Pagina |
|---|---|
| Capire le scelte di runtime e client | [Scelte runtime e modello di deployment](../guides/deployment.md) |
| Eseguire con Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Eseguire da VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Eseguire con un binary release | [Runtime binary standalone](../installation/binary.md) |
| Eseguire con Python o source checkout | [Python runtimes](../installation/python.md) |
| Aggiungere ChatGPT come client | [ChatGPT connector](chatgpt-connector.md) |
| Scegliere strumenti e scrivere prompt migliori | [Modelli di utilizzo](../guides/usage-patterns.md) |
| Collegare una macchina HPC, NPU/GPU o NAT | [Worker remoti](../guides/remote-workers.md) |
| Capire tutti gli strumenti MCP | [Riferimento strumenti](../reference/tools.md) |
