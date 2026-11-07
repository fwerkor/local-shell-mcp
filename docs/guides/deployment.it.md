<!-- i18n-source-sha256: 594169d44520f8abd7cebee1bfa42c5ff0ca31f424115d438107ed01b77fa604 -->
# Scelte del runtime e modello di deployment

`local-shell-mcp` ha due decisioni complementari:

1. **Runtime**: come viene eseguito il processo server e quale workspace controlla.
2. **Interfaccia**: utilizza [unified web workspace](../getting-started/web-workspace.md) opzionale o collega un client MCP esterno come Gemini o ChatGPT.

L'interfaccia quotidiana consigliata è lo spazio di lavoro web self-hosted (chat, progetti e pagine di controllo LSM). Viene distribuito separatamente dal Controller. Docker, l'estensione VS Code, i file binari di rilascio, le installazioni Python e la modalità stdio sono modi per eseguire il controller; le app di chat esterne rimangono client opzionali.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Componi solo HTTP locale Spazio di lavoro Web unificato
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Una configurazione self-hosting comune è:

```text
Browser -> https://chat.example.com (area di lavoro web unificata)
        -> Controller autenticato local-shell-mcp
        -> Spazio di lavoro controllato e Lavoratori in uscita
Client esterno opzionale -> https://mcp.example.com/mcp
```

Una configurazione con MCP client locale può essere più semplice:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

## Matrice di scelta del runtime

| Durata | Meglio per | Confine di isolamento | Fonte della catena di strumenti | Accesso MCP esterno | Pagina |
|---|---|---|---|---|---|
| Docker Componi | La maggior parte dei carichi di lavoro dell'agente di codifica e delle aree di lavoro ripetibili | Contenitore | Immagine del controllore snello; installare separatamente le toolchain specifiche per attività | Aggiungi proxy o tunnel HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + sidecar tunnel | Distribuzione del controller pubblico con Cloudflare Tunnel | Contenitore | Immagine del progetto | Integrato nel profilo Compose `tunnel` | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Avvio/arresto server da editor workspace | Di solito processo host | Strumenti host più executable configurato | Aggiungi tunnel/proxy HTTPS esterno per ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Host o VM senza Docker | Host or VM | Strumenti host più executable configurato | Aggiungi proxy HTTPS o tunnel | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Uso Python-native, debugging, development | Host virtualenv or VM | Package Python più strumenti host | Aggiungi proxy HTTPS o tunnel | [Python install](../installation/python.md) |
| Stdio mode | MCP client locali che avviano processi direttamente | Client process boundary | Strumenti host più executable configurato | Non utilizzabile da ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Matrice connessione client

| Interfaccia | Richiede HTTPS pubblico | Utilizza `/mcp` | Richiede OAuth | Autonomia tipica |
|---|---:|---:|---:|---|
| Spazio di lavoro web LSM unificato | Sì per l'accesso remoto; possibile anche proxy locale | Internamente | Accesso all'LSM | Controller più stack web separato |
| Gemini Spark/App personalizzate | Sì | Sì | Sì, per uso pubblico | Qualsiasi controller HTTP |
| ChatGPT custom MCP connector | Sì | Sì | Sì per uso pubblico | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | No | No | No | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Di solito no su localhost; sì tra reti | Sì | Consigliato fuori da localhost | Any HTTP runtime |
| VS Code extension helper flow | Solo se ChatGPT deve collegarsi | Sì quando si copia URL ChatGPT | Consigliato per ChatGPT | VS Code-launched runtime |

Vedi [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) e [network connectivity](../clients/connectivity.md).

## Cosa controlla ogni runtime

Ogni runtime avvia lo stesso codice server ed espone le stesse famiglie di MCP tools quando abilitate:

- Shell e persistent shell sessions.
- Filesystem, search e patch tools.
- Operazioni Git.
- Browser automation tramite Playwright.
- Audit log e task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle e machine-routed tools.

La differenza non è l’API astratta ma l’**operating environment** dietro di essa.

| Domanda | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Dove vengono eseguiti i comandi? | Dentro il container | Di solito nel workspace host | Nell’ambiente di processo host o VM |
| Workspace predefinito? | Mounted `/workspace` | Cartella VS Code corrente o path configurato | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Compilatori e browser sono preinstallati? | NO; installare ciò di cui ha bisogno l'attività | Solo se installato sull'host | Solo se installato sull'host |
| Facile da resettare? | Ricrea container e volume workspace | Dipende dal workspace | Dipende da host/VM |
| Adatto a installazioni arbitrarie? | Sì, se disposable | Più rischioso su host | Più rischioso fuori da VM |

## Selezione consigliata

Utilizza prima **Docker Compose**, a meno che tu non abbia un motivo per non farlo. Fornisce un chiaro confine di sicurezza senza richiedere una grande toolchain di sviluppo preinstallata.

Utilizza l'**estensione VS Code** quando il flusso di lavoro inizia da un editor e desideri un launcher locale. È ancora in fase di esecuzione. I client Web remoti necessitano di un proxy o tunnel HTTPS raggiungibile.

Usa **standalone binary** quando Docker non è disponibile ma VM, container host o account dedicato forniscono già un confine.

Usa **`pipx` o source install** per development/debugging di `local-shell-mcp` o quando un ambiente Python è più facile da mantenere.

Usa **stdio mode** solo con MCP client locali che possono avviare il processo server. Non è un deployment pubblico e non è utilizzabile direttamente da ChatGPT web/app.

## Regola dell’endpoint pubblico

Per i client MCP HTTP esterni come Gemini e ChatGPT, l'endpoint MCP è:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` contiene solo l’origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Non aggiungere `/mcp` a `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Pagine runtime

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Pagine client

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
