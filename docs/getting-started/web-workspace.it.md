<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# Spazio di lavoro Web unificato

L'**area di lavoro web LSM unificata** è il modo consigliato per utilizzare local-shell-mcp quotidianamente. Combina la chat AI, la cronologia del progetto e il piano di controllo LSM in un'unica interfaccia reattiva, basata su un frontend LibreChat modificato e venduto. Puoi comunque connettere client MCP esterni come [ChatGPT](chatgpt-connector.md) o [Gemini](gemini-spark.md).

Lo spazio di lavoro è **auto-ospitato e installabile facoltativamente**: è un servizio Web separato, non parte dell'immagine minima del Controller, dell'eseguibile autonomo o del bundle Worker remoto. Le distribuzioni solo controller mantengono l'interfaccia utente del browser originale e OpenTUI.

## Cosa c'è nell'area di lavoro?

| Zona | Cosa puoi fare |
|---|---|
| Chat e progetti | Scegli un modello configurato, crea conversazioni, organizza progetti, trova le chat passate e archivia le conversazioni. La cronologia rimane sul server. |
| Panoramica del controllore | Visualizza lo stato, l'attività recente e le macchine connesse. |
| File | Sfoglia e gestisci file locali o remoti. |
| Terminali | Lavora con terminali persistenti sul Controller o sui Worker. |
| Desktop | Ispeziona e controlla le sessioni della GUI remota. |
| Sessioni | Ispeziona le attività LSM durevoli e il loro ciclo di vita. |
| Telecomandi | Connetti e amministra i lavoratori in uscita. |
| Controllo | Ispezionare l'attività dello strumento originato dal modello. |
| MCP nidificato | Registra, modifica, abilita, disabilita, aggiorna e rimuovi server MCP esterni dietro LSM. |

I percorsi del Controller sono `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` e `/control/audit`. La chat si apre su `/c/new`. Il gestore MCP LSM controlla il **registro MCP nidificato di LSM**; non crea un secondo registro in LibreChat.

## Distribuisci lo stack di chat opzionale

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## Accedi e usa la chat

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

I caricamenti di chat (fino a 32 MiB) vengono archiviati nell'area di lavoro del Controller e i relativi percorsi assoluti vengono forniti al modello. I caricamenti nel browser non concedono autorizzazioni aggiuntive per i file. Le chiamate agli strumenti rivolti al modello passano attraverso l'autorizzazione LSM, l'audit e il router del lavoratore remoto.

## MCP esterno, sicurezza e dati

Utilizzare la barra laterale MCP dell'area di lavoro per gestire server MCP esterni nidificati. Supporta server stdio locali e server HTTP, incluse variabili di ambiente private separate e intestazioni di richiesta. I segreti non vengono restituiti al browser. L'attivazione/disattivazione della chat **MCP esterno** consente la ricerca, l'ispezione e l'invocazione di strumenti nidificati; non garantisce il modello `mcp_manage` quando gli strumenti LSM nativi sono disabilitati. La gestione dell'interfaccia utente è protetta dalla normale autorizzazione del Controller.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Risoluzione dei problemi

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Per dettagli sull'implementazione e aggiornamenti, vedere [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) e [human interface guide](../guides/human-interface.md).
