<!-- i18n-source-sha256: 474398c2065f510156f7fba24967ca8f6600b586ffb1e002416b7a10dc34c3dc -->
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

1. [Install and start an LSM Controller](quickstart.md) mit OAuth, einem entsprechend isolierten Arbeitsbereich und persistentem `file`- oder `redis`-Statusspeicher. Installieren Sie Docker Compose und klonen Sie das Repository auf den Host, auf dem der Web-Stack ausgeführt wird.
2. Stellen Sie **zwei HTTPS-Ursprünge auf derselben Site** bereit, z. B. `https://lsm.example.org` für Controller und `https://chat.example.org` für den Arbeitsbereich. Der Chat-Dienst ist nicht direkt in einem nicht vertrauenswürdigen Netzwerk verfügbar.
3. Generieren Sie ein Bridge-Geheimnis mit `openssl rand -hex 32`. Konfigurieren Sie diese Umgebungsvariablen im **Controller-Dienst** mit diesem Geheimnis und starten Sie ihn dann neu:

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. Konfigurieren Sie im Repository-Checkout den optionalen Web-Stack. Verwenden Sie eine private Umgebungsdatei oder exportieren Sie die unten gezeigten Werte. Generieren Sie einzigartige, starke Geheimnisse und geben Sie sie nicht weiter:

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Rendern Sie die private Konfiguration, erstellen und starten Sie dann den separat bereitgestellten Chat-Stack:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

Bei Verwendung der Root-Docker-Compose-Bereitstellung gehören die oben genannten Controller-Variablen in den Root-`.env` und werden an den Container weitergeleitet. Die Chat-Service-Werte können über Shell-Exporte oder eine private Umgebungsdatei bereitgestellt werden. Der Controller-Container muss über den Chat-Container unter `http://local-shell-mcp:8765` im benannten Docker-Netzwerk erreichbar sein. Reverse-Proxy-Port `127.0.0.1:3080` zum Chat-HTTPS-Ursprung, beibehalten Sie den externen Host und folgen Sie [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) im Repository. Auf dem Webstack werden Node.js, MongoDB, Meilisearch und SearXNG ausgeführt. Sie sind **nicht** in den Arbeitern enthalten. Diese separate Bereitstellung wird nicht durch einen einfachen `docker compose up -d` im Repository-Stammverzeichnis gestartet.

## Melden Sie sich an und nutzen Sie den Chat

1. Öffnen Sie `https://lsm.example.org/ui`, authentifizieren Sie sich mit dem **LSM Controller**-Login und folgen Sie der einmaligen Übergabe in den Web-Arbeitsbereich. Sie erstellen kein zweites LibreChat-Benutzerkonto.
2. Konfigurieren Sie einen verfügbaren LLM-Anbieter oder Modellendpunkt für den Chat-Dienst. Der Arbeitsbereich stellt die Chat-Schnittstelle und die Tool-Bridge bereit; **Es beinhaltet weder ein Modell noch API-Credits**.
3. Erstellen Sie ein Gespräch. Websuche und LSM-Tools sind standardmäßig aktiviert und unterliegen den Controller-Berechtigungen. Verwenden Sie je nach Bedarf die konversationsspezifischen Steuerelemente **Web**, **LSM**, **External MCP** und **Memory**.
4. Beginnen Sie mit einer schreibgeschützten Anfrage: „Überprüfen Sie den Controller-Status und listen Sie das Arbeitsbereichsstammverzeichnis auf. Ändern Sie keine Dateien.“
5. Navigieren Sie zu **Dateien**, **Terminals**, **Desktop**, **Sitzungen**, **Remotes** oder **Audit** für eine direkte Inspektion und Kontrolle.

Chat-Uploads (bis zu 32 MiB) werden im Controller-Arbeitsbereich gespeichert und ihre absoluten Pfade werden dem Modell bereitgestellt. Browser-Uploads gewähren keine zusätzlichen Dateiberechtigungen. Modellbezogene Toolaufrufe durchlaufen die LSM-Autorisierung, die Prüfung und den Remote-Worker-Router.

## Externes MCP, Sicherheit und Daten

Verwenden Sie die MCP-Seitenleiste des Arbeitsbereichs, um verschachtelte externe MCP-Server zu verwalten. Dies unterstützt lokale Standardserver und HTTP-Server, einschließlich separater privater Umgebungsvariablen und Anforderungsheader. Geheimnisse werden nicht an den Browser zurückgegeben. Der Chat-Schalter **Externes MCP** ermöglicht die Suche, Überprüfung und den Aufruf verschachtelter Tools; Das Modell `mcp_manage` wird nicht gewährt, wenn native LSM-Tools deaktiviert sind. Die UI-Verwaltung ist durch die normale Controller-Autorisierung geschützt.

Chat-Nachrichten, Projekte und Archive werden serverseitig in der MongoDB des Web-Stacks gespeichert; Die Suche verwendet Meilisearch. Der Controller besitzt separat Tool-Berechtigungen, Worker-Identitäten, Sitzungsstatus und Audit. Sichern Sie beide Datenspeicher, wenn Sie den gesamten Verlauf aufbewahren müssen. Das Chat-Backend ist für Einzelbenutzer unter dem LSM-Login verfügbar. Machen Sie seine interne API oder Datenbanken nicht der Öffentlichkeit zugänglich.

Die Benutzeroberfläche ist eine Top-Level-App, **kein Iframe**. Wenn der optionale Chat-Dienst nicht konfiguriert ist, stellt `/ui` weiterhin die ursprüngliche LSM-WebUI bereit. Natives OpenTUI und externe Clients werden weiterhin unterstützt.

## Fehlerbehebung

- **Umleitung bleibt auf der ursprünglichen Benutzeroberfläche:** Überprüfen Sie `LOCAL_SHELL_MCP_LIBRECHAT_URL`, ein persistentes Controller-Status-Backend und den HTTPS-Reverse-Proxy des Web-Stacks.
- **Anmeldung oder Übergabe schlägt fehl:** Überprüfen Sie auf beiden Seiten genau das gleiche 32-Byte- oder längere Bridge-Geheimnis, das mit denselben Site-Ursprüngen, HTTPS und Serveruhren übereinstimmt.
- **Chat wird geladen, kann aber nicht antworten:** Richten Sie einen tatsächlichen Modellendpunkt oder API-Anmeldeinformationen ein und überprüfen Sie die Chat-Containerprotokolle.
- **MCP-Tools fehlen:** Controller-Bereiche und Konversationsumschaltungen überprüfen; Die verschachtelte Serverregistrierung ist von der LibreChat MCP-Datenbank getrennt.
- **Dateien oder Sitzungen werden leer angezeigt:** Überprüfen Sie, ob der Chat den richtigen Controller und Arbeitsbereich erreicht, und überprüfen Sie seine API-Authentifizierungsprotokolle.

Einzelheiten zur Implementierung und Aktualisierungen finden Sie unter [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) und [human interface guide](../guides/human-interface.md).
