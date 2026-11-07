<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# Avvio rapido

Questa guida avvia un controller LSM e apre la sua interfaccia browser. Lo [unified web workspace](web-workspace.md) è l'esperienza quotidiana consigliata; è uno stack di chat facoltativo distribuito separatamente. ChatGPT, Gemini e altri client MCP esterni possono connettersi allo stesso Controller. Vedi [runtime choices and deployment model](../guides/deployment.md).

È consigliata la **distribuzione diretta dal codice sorgente** in un ambiente isolato. Docker Compose è un’alternativa.

## Requisiti

- Git e Python 3.11+ con `venv` e `pip`.
- HTTPS pubblico solo per utenti remoti o client MCP esterni.
- Directory di lavoro dedicata e limitata.
- PIN amministratore OAuth robusto e segreto JWT casuale.

!!! warning
    Il modello connesso può operare il workspace configurato. Esegui il servizio in un container o VM usa e getta ed evita di montare risorse di controllo dell’host.

## 1. Clonare e configurare

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

Modificare `.env` sostituendo PIN e segreto JWT di esempio (usare `openssl rand -hex 32`). L’esecuzione da sorgenti non carica automaticamente `.env`.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Avviare il server

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Verificare lo stato in un secondo terminale:

```bash
curl -i http://127.0.0.1:8765/healthz
```

La risposta corretta è HTTP `200`. Per un servizio permanente utilizzare un gestore di servizi.

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

Aggiornare i sorgenti, reinstallare il pacchetto editable e riavviare il Controller:

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

Per Docker Compose aggiornare invece il container:

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
