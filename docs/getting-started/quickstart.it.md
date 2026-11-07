<!-- i18n-source-sha256: 8c51015fb3cc5269af4d5bf07eddfa8deac64e90f0063ee8cd1fc661439f7679 -->
# Avvio rapido

Questa guida avvia un controller LSM e apre la sua interfaccia browser. Lo [unified web workspace](web-workspace.md) è l'esperienza quotidiana consigliata; è uno stack di chat facoltativo distribuito separatamente. ChatGPT, Gemini e altri client MCP esterni possono connettersi allo stesso Controller. Vedi [runtime choices and deployment model](../guides/deployment.md).

## Requisiti

- Docker Engine con Compose v2.
- Un endpoint HTTPS pubblico se devono connettersi utenti remoti o client MCP esterni.
- Una directory workspace dedicata.
- Un OAuth admin PIN e JWT secret lunghi e casuali.

!!! warning
    Il modello connesso può operare il workspace configurato. Esegui il servizio in un container o VM usa e getta ed evita di montare risorse di controllo dell’host.

## 1. Clonare e configurare

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
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

## 4. Aprire l'area di lavoro del browser

Apri il login del Controller:

```text
https://your-public-host.example.com/ui
```

Per chat, progetti e pagine di controllo integrate, segui [unified web workspace guide](web-workspace.md). La WebUI leggera originale è disponibile quando la chat non è installata.

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
| Utilizza la chat unificata e l'interfaccia di controllo | [Unified web workspace](web-workspace.md) |
| Aggiungi Gemini Spark come client | [Gemini Custom Apps](gemini-spark.md) |
| Aggiungere ChatGPT come client | [ChatGPT connector](chatgpt-connector.md) |
| Scegliere strumenti e scrivere prompt migliori | [Modelli di utilizzo](../guides/usage-patterns.md) |
| Collegare una macchina HPC, NPU/GPU o NAT | [Worker remoti](../guides/remote-workers.md) |
| Capire tutti gli strumenti MCP | [Riferimento strumenti](../reference/tools.md) |
