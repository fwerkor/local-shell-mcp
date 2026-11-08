<!-- i18n-source-sha256: ed47d5e0691f17af5cd4758981c31957e299202bf72433b34b4656346312091e -->
# Runtime binario autonomo

È consigliato il **singolo eseguibile del Controller** di GitHub Releases, senza Python, Docker o checkout sorgente.

Questa è una scelta di runtime. L’accesso ChatGPT viene configurato separatamente tramite un endpoint HTTPS `/mcp`.

## Artifact di release

GitHub Releases costruisce executables autonomi per le piattaforme comuni:

| Platform artifact | Archive |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

Ogni archive contiene executable, README, license e un breve file quickstart.

È disponibile anche un **eseguibile singolo**. Contiene solo Controller e WebUI nativa; chat, database, Worker, strumenti di sviluppo e browser sono separati.

## Installazione

1. Scaricare il file eseguibile o archivio corretto da [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest).
2. Se si usa un archivio, estrarlo.
3. Metti l’executable nel `PATH` o annota il percorso assoluto.
4. Esegui `local-shell-mcp --help` per verificare che il binary si avvii.

Esempio: download diretto del file Linux x86_64; scegliere il pacchetto appropriato per altre piattaforme:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
```

Su Windows esegui `local-shell-mcp.exe` da PowerShell o aggiungi la directory che lo contiene al `PATH`.

## Esecuzione locale minima

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
~/lsm/local-shell-mcp --mode mcp
```

In un altro terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Esecuzione pubblica HTTP MCP

Per ChatGPT o un public HTTP MCP client, configura queste categorie:

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | Directory controllata dagli strumenti |
| `LOCAL_SHELL_MCP_HOST` and `LOCAL_SHELL_MCP_PORT` | Indirizzo bind e porta locali |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | Public HTTPS origin, senza `/mcp` |
| `LOCAL_SHELL_MCP_AUTH_MODE` | Usa `oauth` per deployment pubblici |
| OAuth PIN and JWT secret settings | Necessari per autorizzazione OAuth pubblica |

Esponi la porta HTTP locale tramite reverse proxy o tunnel. L’endpoint pubblico è:

```text
https://your-public-host.example.com/mcp
```

## Configurazione YAML

Un YAML config può contenere default runtime non segreti:

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

Esegui:

```bash
local-shell-mcp --config /path/to/config.yaml
```

Le environment variables con prefisso `LOCAL_SHELL_MCP_` sovrascrivono i valori YAML.

## Responsabilità del host toolchain

Il binary include l’applicazione Python, non ogni strumento di sviluppo. Gli strumenti MCP chiamano programmi disponibili sull’host.

Installa ciò che serve alle tue attività:

| Capability | Host packages to consider |
|---|---|
| Search and shell ergonomics | `ripgrep`, `tree`, `jq`, `curl`, `wget`; le release Linux includono già static tmux helper |
| Git workflows | `git`, `gh`, OpenSSH client, credential helpers |
| Python projects | Python, pip, venv, project-specific compilers and headers |
| Node projects | Node.js, npm, pnpm, yarn |
| Rust/Go/Java/C++ | Cargo/rustc, Go, JDK, Maven/Gradle, compilers, CMake, Ninja |
| Browser automation | Playwright browser binaries and OS dependencies |
| Document conversion | LibreOffice, Pandoc, Poppler utilities |

Il binario include il Controller; strumenti esterni e browser sono opzionali. Chat e cronologia richiedono il [workspace web](../getting-started/web-workspace.md) e database separati.

## Servizio persistente

Per un deployment pubblico persistente, esegui il binary sotto il process supervisor del sistema operativo. Mantieni queste pratiche:

- Usa un account OS dedicato con pochi privilegi.
- Usa un workspace directory dedicato.
- Conserva i valori sensibili fuori dai file world-readable.
- Riavvia automaticamente in caso di errore.
- Controlla `/healthz` dopo ogni riavvio.
- Mantieni i log disponibili per troubleshooting.

## Aggiornamenti

1. Sostituire l’eseguibile e riavviare il Controller:
2. Verifica i checksum se vuoi.
3. Sostituisci l’executable.
4. Riavvia il process manager.
5. Controlla `/healthz`.
6. Chiedi al client di eseguire `environment_get` prima di continuare.

## Note di sicurezza

Il binary viene eseguito con i privilegi del suo utente del sistema operativo. Per deployment pubblici usa un utente dedicato a bassi privilegi, un workspace dedicato e, se possibile, un confine VM/container.

Non impostare `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` per un binary eseguito direttamente sul tuo host personale. Questa impostazione è destinata a containers o VM usa e getta.
