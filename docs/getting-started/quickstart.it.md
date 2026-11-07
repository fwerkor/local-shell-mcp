<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Avvio rapido

Questa guida avvia un controller LSM e apre la sua interfaccia browser. Lo [unified web workspace](web-workspace.md) è l'esperienza quotidiana consigliata; è uno stack di chat facoltativo distribuito separatamente. ChatGPT, Gemini e altri client MCP esterni possono connettersi allo stesso Controller. Vedi [runtime choices and deployment model](../guides/deployment.md).

È consigliato il **singolo eseguibile del Controller** di [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest), senza Python, Docker o checkout sorgente. Esempio per **Linux x86_64**; altre piattaforme: [installazione binaria](../installation/binary.md).

## Requisiti

- Eseguibile per la piattaforma e `curl` (Linux x86_64).
- HTTPS pubblico solo se necessario per accessi remoti o client MCP esterni.
- Workspace dedicato e limitato.
- PIN amministratore OAuth robusto e segreto JWT casuale.

!!! warning
    Il modello connesso può operare il workspace configurato. Esegui il servizio in un container o VM usa e getta ed evita di montare risorse di controllo dell’host.

## 1. Scaricare e configurare il binario

Scaricare l’eseguibile singolo e generare il segreto JWT:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

Creare `.env` e sostituire PIN e segreto JWT di esempio (usare `openssl rand -hex 32`). Il binario **non carica automaticamente** `.env`.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Avviare il server

Avviare direttamente l’eseguibile:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Verificare lo stato in un altro terminale:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Una risposta corretta restituisce HTTP `200`. Per uso permanente adottare un supervisore e account limitato.

## 3. Esporre HTTPS

Per l’accesso remoto usare un server pubblico o un reverse proxy HTTPS (Caddy, Nginx, Traefik), inoltrando tutto il sito inclusi upload e download a:

```text
http://127.0.0.1:8765
```

Verificare HTTPS:

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel è sconsigliato** per i file: gli upload dal client possono essere lenti. Preferire server pubblici o un normale reverse proxy/inoltro porte mantenendo OAuth. Alternativa: [Docker](../installation/docker.md).

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

Sostituire l’eseguibile e riavviare il Controller:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Per Docker Compose aggiornare il container. Guida sorgenti: [Python](../installation/python.md).

```bash
docker compose pull
docker compose up -d
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
