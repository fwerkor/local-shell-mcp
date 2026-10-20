<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Remote Worker

Remote Worker ermöglichen `local-shell-mcp` die Steuerung von Maschinen, die ausgehende HTTP(S)-Anfragen senden können, aber keine eingehenden SSH-Verbindungen akzeptieren können.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Grundablauf

1. Erstellen Sie mit `remote_manage(action="invite", ...)` eine Einladung.
2. Führen Sie den erzeugten Befehl auf der Remote-Maschine aus.
3. Bestätigen Sie die Registrierung mit `remote_manage(action="list")`.
4. Rufen Sie normale Tools mit `machine="<worker-name>"` auf, zum Beispiel `environment_get`, `run_shell`, `file_read` oder `browser_run_script`.
5. Starten Sie mit `remote_transfer` einen verfolgten controller-to-worker-, worker-to-controller- oder worker-to-worker-Datei-/Verzeichnistransfer. Beobachten Sie ihn mit `job_list` oder `job_tail`; stoppen oder wiederholen Sie ihn mit `job_stop` bzw. `job_retry`.
6. Benennen Sie Worker mit `remote_manage(action="rename", ...)` um oder widerrufen Sie sie mit `remote_manage(action="revoke", ...)`.

Eine Einladung registriert standardmäßig einen Worker (`max_uses=1`). Erhöhen Sie `max_uses`, um mehrere Worker mit derselben Einladung zu registrieren. Lassen Sie `name` bei mehrfach verwendbaren Einladungen leer. Der optionale Wert `ttl_s` beträgt standardmäßig zwei Stunden (7200 Sekunden) und kann auf höchstens sieben Tage (604800 Sekunden) gesetzt werden.

Nur die Worker-Administration verwendet `remote_*`-Namen. Execution-, Shell-, Job-, Filesystem-, Patch- und Browser-Operationen nutzen lokal und remote dasselbe Schema. Die Angabe einer Machine erfordert zusätzlich den OAuth-Scope `remote:use`.

## Persistente Worker

Das Einladungsergebnis enthält plattformspezifische Befehle:

- `persistent_command` installiert und startet unter Linux oder macOS einen User-Service.
- `powershell_persistent_command` installiert und startet unter Windows eine User-Task aus PowerShell.

Unter Windows registriert `local-shell-mcp worker install-service` die Task `local-shell-mcp-worker` für den aktuellen Benutzer. Sie startet sofort, startet nach einem Reboot beim nächsten Login dieses Benutzers erneut, erlaubt Batteriebetrieb, ignoriert Doppelstarts und wiederholt fehlgeschlagene Läufe. Administratorrechte sind nicht erforderlich und sie läuft nicht vor der Anmeldung des Benutzers.

Verwenden Sie auf allen Plattformen dieselben Lifecycle-Befehle:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

Das Worker-Log liegt als `worker.log` im Worker-State-Verzeichnis.

## Fähigkeiten

Worker unterstützen Shell/Persistent-Shell-Sitzungen, verfolgte Jobs, Filesystem-Operationen, Transfer-Interna, Python-Ausführung, Patches sowie Playwright, sofern die Abhängigkeiten installiert sind. Git verwendet Standardbefehle über `run_shell(machine=...)`.

## Sicherheit und Versionierung

Ein verbundener Worker gibt dem MCP client Kontrolle über seine konfigurierte Umgebung. Verwenden Sie kurze Invite-TTLs, dedizierte Arbeitsverzeichnisse oder Benutzerkonten, prüfen Sie Audit-Logs und widerrufen Sie Worker nach der Aufgabe. Die generierte Einladung installiert Worker-Code, der zur Version des Kontrollservers passt.

## Fehlerbehebung

Wenn ein Worker nicht erscheint, prüfen Sie ausgehenden HTTPS-Zugriff, Erreichbarkeit der Public Base URL, Ablauf der Einladung, Systemzeit und Logs des Kontrollservers.
