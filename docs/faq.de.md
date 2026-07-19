# Häufig gestellte Fragen

Diese Seite behandelt wiederkehrende Client- und Reverse-Proxy-Probleme, die wie LSM-Fehler wirken können, obwohl der Server selbst fehlerfrei läuft.

## Warum fehlen nach einem LSM-Upgrade einige Werkzeuge in ChatGPT?

### Symptome

- Neue Werkzeuge werden in ChatGPT nicht angezeigt.
- ChatGPT versucht weiterhin, ein entferntes, umbenanntes oder zusammengeführtes Werkzeug aufzurufen.
- Das Werkzeug existiert, aber der Aufruf scheitert, weil ChatGPT ein älteres Eingabeschema sendet.
- Ein Neustart von LSM oder eine neue Unterhaltung behebt das Problem nicht.

### Ursache

ChatGPT kann einen eingefrorenen Snapshot der Werkzeuge und Eingabeschemata behalten, die beim Scannen, Genehmigen oder Veröffentlichen einer MCP App verfügbar waren. Wenn eine LSM-Version `tools/list` ändert, wird dieser Snapshot nicht garantiert automatisch aktualisiert. Es handelt sich nicht um einen kurzlebigen Cache mit dokumentierter Ablaufzeit.

### Lösung

=== "Entwicklermodus oder persönliche Verbindung"

    1. Öffnen Sie **ChatGPT Settings → Apps**.
    2. Öffnen Sie die LSM App und führen Sie mit **Refresh** einen erneuten Scan durch.
    3. Falls Refresh fehlt, löschen Sie die alte App und fügen denselben MCP-Endpunkt erneut hinzu.
    4. Starten Sie nach der Übernahme der neuen Werkzeugliste eine neue Unterhaltung.

=== "Veröffentlichte App in ChatGPT Business"

    Eine veröffentlichte benutzerdefinierte App kann ihre Werkzeuge oder Metadaten derzeit nicht direkt aktualisieren. Ein Administrator muss eine neue App erstellen, den aktuellen LSM-Endpunkt scannen, den Ersatz veröffentlichen und die alte App außer Betrieb nehmen.

=== "ChatGPT Enterprise oder Edu"

    Ein Administrator kann **Workspace Settings → Apps → LSM App → … → Action control → Refresh** öffnen, die Änderungen prüfen und neue Actions bei Bedarf aktivieren.

Siehe [Issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) und die [OpenAI-Dokumentation zu MCP Apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## Warum verbindet sich die WebUI hinter Nginx ständig neu?

### Symptome

- WebUI und OAuth-Anmeldung werden normal geladen.
- Die TUI erscheint nicht.
- Der Status wechselt ständig zwischen `Connecting`, `Connection error` und `Reconnecting`.
- Der direkte Zugriff auf Port `8765` funktioniert.

### Ursache

Die Browseroberfläche rendert die native TUI über einen PTY WebSocket. Der Standardendpunkt ist `/ui/ws`; bei einem benutzerdefinierten `ui_path` lautet er `${ui_path}/ws`. Ein normales Nginx-`proxy_pass` leitet die für das WebSocket-Upgrade nötigen hop-by-hop-Header nicht automatisch weiter.

### Lösung

Aktivieren Sie HTTP/1.1 und leiten Sie `Upgrade` und `Connection` weiter:

```nginx
# map gehört in den http-Block.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

Prüfen und laden Sie Nginx anschließend neu:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Aktivieren Sie in Nginx Proxy Manager **Websockets Support** für den Proxy Host. Bei weiteren Verbindungsversuchen ergänzen Sie die entsprechenden Header unter Advanced.

### Prüfung

Öffnen Sie die Browser-Entwicklertools, laden Sie WebUI neu und prüfen Sie die Anfrage `/ui/ws`. Eine funktionierende Verbindung liefert:

```text
101 Switching Protocols
```

Siehe [Issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
