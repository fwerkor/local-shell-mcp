<!-- i18n-source-sha256: a66d491558f07c419c8b5958d36c47cd90b081fc1c81f015bb62398cfd573e55 -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">Selbstgehosteter KI-Arbeitsbereich · MCP-Steuerungsebene</span>

# local-shell-mcp

Chat, Projekte, Dateien, Terminals, Remote-Maschinen und KI-Tools in einer selbst gehosteten Oberfläche. Schließen Sie externe MCP-Clients an, wenn Sie sie benötigen.

<div class="hero-actions" markdown>
[Loslegen](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Tool-Referenz](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Echte Coding-Umgebung
Führen Sie Tests aus, untersuchen Sie Repositories, patchen Sie Dateien, bedienen Sie Git und führen Sie einen Audit Trail über einen MCP-Endpoint.
</div>

<div class="feature-card" markdown>
### Einheitlicher Web-Arbeitsbereich
Nutzen Sie den integrierten Chat- und Projektverlauf neben Controller-Dateien, Terminals, Desktops, Sitzungen, Remotes und Audits. Externe MCP-Clients bleiben optional.
</div>

<div class="feature-card" markdown>
### Remote-Maschinensteuerung
Binden Sie NAT-, Firewall- oder HPC-Maschinen über ausgehende Worker-Verbindungen ein, ohne SSH-Ports zu öffnen.
</div>
</div>

## Was es bereitstellt

`local-shell-mcp` bietet einen einheitlichen, selbst gehosteten KI-Arbeitsbereich und einen MCP-Server für externe Clients. Es bietet Shell, persistente Shell, Dateisystem, Suche, Patch, Git, Playwright, Audit, dauerhafte logische Sitzungen mit optionalen Zielplänen, tokenisierte Dateiverknüpfung und Remote-Worker-Tools über authentifizierte MCP-Endpunkte.

Verwenden Sie es, wenn die KI ein Repository untersuchen, Tests ausführen, Dateien bearbeiten, Git bedienen, Browser-Evidenz sammeln, herunterladbare Artefakte erzeugen oder eine Remote-Maschine steuern muss, die nur ausgehend zum Control Server verbinden kann.

## Architektur

```text
Runtime-Ebene: Docker / VS Code extension / binary / Python / stdio
Exposure-Ebene: localhost / HTTPS proxy / tunnel / stdio pipe
Client-Ebene: einheitlicher WebUI-/Gemini-/ChatGPT-/generischer MCP-Client
Kontrollierter Workspace: /workspace or configured workspace root
Optionale Remote workers: outbound machine connections
```

Die vorgesehene Isolationsgrenze ist der Container oder die VM, in der der Dienst läuft.

## Nach Szenario beginnen

| Szenario | Startpunkt | Warum |
|---|---|---|
| Primärer Browser-Arbeitsbereich | [Unified web workspace](getting-started/web-workspace.md) | Chat, Projekte und LSM-Kontrollseiten mit einem gemeinsamen Login |
| Erste Controller-Bereitstellung | [Quickstart](getting-started/quickstart.md) | Docker Compose, OAuth und die erste Browsersitzung |
| Runtime-Ebene auswählen | [Runtime choices](guides/deployment.md) | Erklärt Docker, VS Code, binary, Python und stdio als getrennte Runtime-Optionen |
| Zwillinge Spark verbinden | [Gemini Custom Apps](getting-started/gemini-spark.md) | Berechtigung, HTTPS-MCP-URL, OAuth und Tests |
| ChatGPT als Client hinzufügen | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, erster sicherer Prompt und Tool Discovery |
| LSM zu DeepSeek Harness hinzufügen | [DeepSeek-Harness-Plugin](clients/deepseek-harness.md) | Dieses Repository als DSH-Bundle installieren und die vollständige LSM-Tool- und Remote-Worker-Oberfläche beibehalten |
| Aus VS Code ausführen | [VS Code extension runtime](installation/vscode-extension.md) | Editor-gestarteter Runtime und Host-Sicherheitshinweise |
| Toolset bedienen lernen | [Usage patterns](guides/usage-patterns.md) | Prompt-Vorlagen und Tool-Auswahlhilfe |
| Jedes Tool verstehen | [Tools reference](reference/tools.md) | Detaillierte Zwecke, Inputs, Returns, Kombinationen und Hinweise |
| HPC-, NPU/GPU- oder Server-Node verbinden | [Remote workers](guides/remote-workers.md) | Outbound-Worker-Join-Flow und Remote-Tool-Nutzung |
| Generierte Dateien teilen | [File links](guides/file-links.md) | Tokenisierte Download-URLs mit TTL und Widerruf |
| Deployment härten | [Security](security.md) | Isolation, OAuth, Workspace-Scope und Audit Logs |

## Wichtige Toolfamilien

| Familie | Beispiele | Verwendung |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, Tests, Scripts und lang laufende Prozesse |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository-Inspektion und präzise Edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Prüfbare Source-Control-Workflows |
| Sessions und Goals | `session_manage`, `plan_manage` | Dauerhafte Task-Übergabe, Fortschrittsberichte und optionaler Goal Mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistente Interaktion, UI-Checks, Screenshots, gerenderte Docs und Seitentext |
| File links | `link_create`, `link_revoke` | Generierte Artefakte aus dem Chat herunterladen |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | Maschinen hinter NAT, Firewalls oder Cluster-Login-Flows |

## Typische Workflows

### Codierung im Web-Workspace

1. Starten Sie einen LSM-Controller und den optionalen [unified web workspace](getting-started/web-workspace.md).
2. Öffnen Sie `/ui` und melden Sie sich mit der LSM-Identität an.
3. Konfigurieren Sie einen Modellendpunkt und öffnen Sie eine neue Konversation.
4. Bitten Sie das Modell, das Repository zu überprüfen und zunächst schreibgeschützte Prüfungen durchzuführen.
5. Erlauben Sie danach Patches, Tests, Diff-Review, Commit und Push nach Freigabe.
6. Prüfen Sie das Audit Log bei Tasks mit File Links oder Remote-Systemen.

### Remote-HPC- oder Accelerator-Host

1. Erstellen Sie eine einmalige Remote-worker-Einladung.
2. Fügen Sie den generierten Befehl auf dem Remote Host ein.
3. Verwenden Sie normale Tools mit `machine`; Git über `run_shell`, Transfers über `remote_transfer`.
4. Widerrufen Sie den Worker nach der Aufgabe.

### Artefakterzeugung

1. Lassen Sie die KI eine Datei unter `/workspace` erzeugen.
2. Erstellen Sie einen tokenisierten File Link mit TTL/Download-Limits.
3. Teilen Sie den Link im Chat.
4. Widerrufen Sie ihn danach.

## Sprache

Diese Site wird mit dem nativen MkDocs-i18n-Plugin gebaut. Über den Sprachumschalter im Header können Sie zwischen English und übersetzten Seiten wechseln. Seiten ohne Übersetzung fallen auf English zurück.
