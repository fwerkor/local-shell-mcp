<!-- i18n-source-sha256: 382c9edbbba8fa4fb3aab11dcc4127ba80bff8c7104bdedffdf66b9bbcdb744a -->
# Nutzungsmuster und Prompt-Leitfaden

`local-shell-mcp` stellt leistungsfähige Tools bereit. Gute Ergebnisse entstehen, wenn das Modell zuerst prüft, in kleinen Schritten handelt, verifiziert und die Änderungen berichtet.

## Allgemeine Arbeitsfolge

Verwenden Sie für die meisten Coding-Aufgaben diese Schleife:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read` und `run_shell` für Befehle wie `git status`.
2. Plan: Modell soll minimale beteiligte Dateien und Tests identifizieren.
3. Edit: `file_edit`, `file_patch` oder Shell-Befehle verwenden.
4. Verify: gezielte Tests/Builds mit `run_shell` oder persistenten Shells ausführen.
5. Review: `git diff` über `run_shell`, bei Bedarf `secret_scan` und `audit_tail`.
6. Commit/export: explizite Git-CLI-Befehle über `run_shell` oder `link_create`.

## Tool-Auswahl

| Aufgabe | Bevorzugen | Vermeiden |
|---|---|---|
| Kurzer one-shot Befehl | `run_shell` | Für jeden Befehl persistente Shell starten |
| Lang laufender Dev-Server, REPL, Watch-Task | `shell_start` + `shell_read` + `shell_send` | `run_shell` bis Timeout blockieren |
| Strukturierte Analyse oder Dateigenerierung | `run_python` | Fragile Shell-Pipelines für komplexes JSON/Text |
| Kleine exakte Änderung | `file_edit` | Unnötiges Umschreiben ganzer Dateien |
| Eine oder mehrere Ersetzungen in einer Datei | `file_edit` with an `edits` array | Veraltete Edits ohne erneutes Lesen |
| Multi-File-Patch | `file_patch` | Ad-hoc-Shell-Edits |
| Dateien finden | `file_tree`, `file_glob` | Vollständige rekursive Listings großer Repositories |
| Code finden | `file_grep` | Viele Dateien blind lesen |
| Browser-Evidenz | `browser_snapshot`, `browser_run_script` | Aus Seitennamen/Routen raten |
| Downloadbare Artefakte | `link_create` | Große Binärinhalte in Chat einfügen |
| Arbeit auf Remote-Maschine | normal tools with `machine`, plus `remote_transfer` | Inbound SSH öffnen, obwohl Outbound Worker reicht |

## Tools über die CLI aufrufen

Für Shell-Skripte und CI ruft `lsm call <tool>` dieselbe registrierte Tool-Oberfläche über den laufenden Loopback-Controller auf. Dadurch bleiben Remote Worker und Controller-Zustand erhalten.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Mit `--session s_...` lässt sich der Aufruf einer Logical Session zuordnen. Im dokumentierten Docker-Compose-Setup bleibt das rohe `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN` ausschließlich in der zugriffsbeschränkten, hosteigenen `.env`, während Compose nur den SHA-256-Prüfwert an den Controller übergibt; andere getrennte Runtime-Layouts können `--token-file <path>` verwenden. `--direct` umgeht den Controller, wendet die Runtime-Einstellungen der aktuellen `.env` im Prozess an, injiziert das Host-CLI-Token nicht in die Tool-Umgebung und ist nur lokal verfügbar. Das Human-UI-Token wird von `/mcp` niemals akzeptiert; bei getrennten Runtimes muss der Controller den passenden `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256` konfigurieren.

## Prompt-Vorlagen

### Read-only Repository-Orientierung

```text
Verwende local-shell-mcp. Prüfe Repository-Layout und git status. Ändere keine Dateien. Fasse Hauptkomponenten, ableitbare Testbefehle und offensichtliche Risiken zusammen, bevor du Änderungen machst.
```

### Fokussierte Fehlerbehebung

```text
Verwende local-shell-mcp, um den Fehler zu beheben. Reproduziere oder lokalisiere ihn zuerst mit dem kleinsten relevanten Befehl. Lies Dateien vor dem Editieren. Erstelle einen minimalen Patch, führe gezielte Verifikation aus und zeige dann git diff sowie die exakt ausgeführten Tests. Committe erst nach meiner Freigabe.
```

### Commit- und Push-Workflow

```text
Verwende local-shell-mcp. Prüfe git status und diff, führe relevante Tests und secret_scan aus, erstelle einen fokussierten Commit mit knapper Nachricht und pushe dann den aktuellen Branch. Keine Caches, Build-Artefakte oder unbezogene Formatierung.
```

### Lang laufender Prozess

```text
Starte den Dev-Server in einer persistenten Shell-Session, lies den Output bis er ready ist und prüfe die Seite mit Browser-Tools. Behalte die Session-ID und beende sie nach der Prüfung.
```

### Remote-Worker-Aufgabe

```text
Verwende den verbundenen Remote Worker <machine>. Rufe zuerst environment_get mit machine=<machine> auf, danach file_list mit derselben machine. Arbeite nur im konfigurierten Remote-Workdir. Für kurze Befehle run_shell, für lange Aufgaben shell_start oder job_start.
```

## Arbeiten mit Repositories

Empfohlene Reihenfolge für Open-Source-Änderungen:

1. `git status --short --branch` über `run_shell` ausführen.
2. Fetch/Branches mit expliziten Git-CLI-Befehlen prüfen, wenn Upstream-State wichtig ist.
3. Vor Edits `file_grep` und `file_read` verwenden.
4. Minimalen Patch erstellen.
5. Zuerst gezielte Tests, dann nach Möglichkeit breitere Tests.
6. Vor Commit oder Push `secret_scan` ausführen.
7. Explizit stagen und mit knapper Nachricht committen.

Bitten Sie um einen Commit pro logischer Änderung, wenn Maintainer prüfbare Historie benötigen.

## Arbeiten mit generierten Artefakten

Für PDFs, Reports, Screenshots, Archive oder Logs:

1. Datei im Workspace erzeugen.
2. Existenz und erwartete Größe prüfen.
3. `link_create` mit kurzer TTL und optionalem `max_downloads` verwenden.
4. Link widerrufen, wenn er nicht mehr benötigt wird.

Keine öffentlichen Links für Private Keys, Credential-Verzeichnisse oder unbezogene persönliche Daten erstellen.

## Arbeiten mit Remote-Maschinen

Remote-Worker-Modus ist nützlich, wenn eine Maschine ausgehende HTTPS-Anfragen machen, aber kein eingehendes SSH annehmen kann.

Empfehlungen:

- Maschinen mit `remote_manage(action="invite", ...)` oder `remote_manage(action="rename", ...)` erstellen/umbenennen.
- Vor Aktionen `environment_get(machine=...)` aufrufen.
- Mit `remote_transfer` Controller/Worker- oder Worker/Worker-Transfer-Jobs starten und mit normalen `job_*`-Tools verwalten.
- Worker nach der Aufgabe mit `remote_manage(action="revoke", ...)` widerrufen.

## Anti-Patterns

Vermeiden Sie diese Anweisungen, außer die Umgebung ist disposable und die Folgen sind verstanden:

- „Installiere global alles Nötige“ auf einem hostgestarteten Server.
- „Lauf, bis es funktioniert“ ohne Zeitgrenzen oder Prüfkriterien.
- „Committe alles“ in einem Repository mit generierten Artefakten.
- „Expose das ganze Home-Verzeichnis“ aus Bequemlichkeit.
- „Erzeuge einen File Link für den gesamten Workspace“.
- Öffentliche Deployments mit `LOCAL_SHELL_MCP_AUTH_MODE=none`.
