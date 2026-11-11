<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# Einheitlicher Web-Arbeitsbereich

Der **einheitliche LSM-Webarbeitsbereich** ist die empfohlene Methode für die tägliche Nutzung von local-shell-mcp. Es kombiniert KI-Chat, Projektverlauf und die LSM-Steuerungsebene in einer reaktionsfähigen Oberfläche, basierend auf einem modifizierten, vom Anbieter bereitgestellten LibreChat-Frontend. Sie können weiterhin externe MCP-Clients wie [ChatGPT](chatgpt-connector.md) oder [Gemini](gemini-spark.md) anschließen.

Der Arbeitsbereich ist **selbstgehostet und kann optional installiert werden**: Es handelt sich um einen separaten Webdienst, nicht Teil des minimalen Controller-Images, der eigenständigen ausführbaren Datei oder des Remote-Worker-Pakets. Bei reinen Controller-Bereitstellungen bleiben die ursprüngliche Browser-Benutzeroberfläche und OpenTUI erhalten.

## Was befindet sich im Arbeitsbereich?

| Bereich | Was Sie tun können |
|---|---|
| Chat und Projekte | Wählen Sie ein konfiguriertes Modell, erstellen Sie Konversationen, organisieren Sie Projekte, finden Sie vergangene Chats und archivieren Sie Konversationen. Der Verlauf verbleibt auf dem Server. |
| Controller-Übersicht | Sehen Sie sich den Zustand, die letzten Aktivitäten und verbundene Maschinen an. |
| Dateien | Durchsuchen und verwalten Sie lokale oder Remote-Dateien. |
| Terminals | Arbeiten Sie mit persistenten Terminals auf dem Controller oder den Workern. |
| Desktop | Überprüfen und steuern Sie Remote-GUI-Sitzungen. |
| Sitzungen | Untersuchen Sie dauerhafte LSM-Aufgaben und ihren Lebenszyklus. |
| Fernbedienungen | Verbinden und verwalten Sie ausgehende Mitarbeiter. |
| Prüfung | Überprüfen Sie die modellbasierte Werkzeugaktivität. |
| Verschachteltes MCP | Registrieren, bearbeiten, aktivieren, deaktivieren, aktualisieren und entfernen Sie externe MCP-Server hinter LSM. |

Die Controller-Routen sind `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` und `/control/audit`. Der Chat wird unter `/c/new` geöffnet. Der LSM MCP-Manager steuert **die verschachtelte MCP-Registrierung von LSM**; Es wird keine zweite Registrierung in LibreChat erstellt.

## Stellen Sie den optionalen Chat-Stack bereit

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

## Melden Sie sich an und nutzen Sie den Chat

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Chat-Uploads (bis zu 32 MiB) werden im Controller-Arbeitsbereich gespeichert und ihre absoluten Pfade werden dem Modell bereitgestellt. Browser-Uploads gewähren keine zusätzlichen Dateiberechtigungen. Modellbezogene Toolaufrufe durchlaufen die LSM-Autorisierung, die Prüfung und den Remote-Worker-Router.

## Externes MCP, Sicherheit und Daten

Verwenden Sie die MCP-Seitenleiste des Arbeitsbereichs, um verschachtelte externe MCP-Server zu verwalten. Dies unterstützt lokale Standardserver und HTTP-Server, einschließlich separater privater Umgebungsvariablen und Anforderungsheader. Geheimnisse werden nicht an den Browser zurückgegeben. Der Chat-Schalter **Externes MCP** ermöglicht die Suche, Überprüfung und den Aufruf verschachtelter Tools; Das Modell `mcp_manage` wird nicht gewährt, wenn native LSM-Tools deaktiviert sind. Die UI-Verwaltung ist durch die normale Controller-Autorisierung geschützt.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

Die Benutzeroberfläche ist eine Top-Level-App, **kein Iframe**. Wenn der optionale Chat-Dienst nicht konfiguriert ist, stellt `/ui` weiterhin die ursprüngliche LSM-WebUI bereit. Natives OpenTUI und externe Clients werden weiterhin unterstützt.

## Fehlerbehebung

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Einzelheiten zur Implementierung und Aktualisierungen finden Sie unter [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) und [human interface guide](../guides/human-interface.md).
