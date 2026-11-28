<!-- i18n-source-sha256: 01cf883cb71925e93fabc21d32315ef8c869ee2ea548e54a0347e2f6b730a327 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Quickstart zum WebUI-Chat

Die einheitliche LSM-Webschnittstelle integriert eine AI-Chat-Funktion, Projekte, Agenten sowie die Bedienoberflächen des Controllers. Sie wird vom Python-Controller gesteuert und nutzt dessen Authentifizierungsmechanismen sowie die SQLite-Datenbank. Es ist keine separate Chat-Serverlösung erforderlich. Externe MCP-Klienten wie [ChatGPT](chatgpt-connector.md) und [Gemini](gemini-spark.md) werden weiterhin unterstützt.

## 1. Controller starten

Folgen Sie der [Installationsanleitung](quickstart.md), um die gewünschte Laufzeitumgebung zu installieren. Stellen Sie sicher, dass die WebUI aktiviert ist und dass eine persistierende Speicherung verwendet wird. Die Standardeinstellungen sind wie folgt:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

Nach dem Export Ihrer Serviceumgebung sollten Sie den Controller starten.

```sh
local-shell-mcp --mode mcp
```

Für die Einzelstrang-Veröffentlichung sollte man stattdessen das heruntergeladene Exeutable verwenden. Der installierte Controller dient dazu, die kompilierten Frontends bereitzustellen; das JavaScript-Build-Toolchain ist nur für die Quellcode-Builds erforderlich. Weitere Informationen finden Sie in den [WebUI-Build-Anleitungen](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## 2. Browser-Arbeitsbereich öffnen

Öffnen Sie die Seite `http://127.0.0.1:8765/ui` vom Controller-Host aus – oder die über die konfigurierte HTTPS-Adresse, die auf `/ui` endet. Melden Sie sich mit der für diese Bereitstellung konfigurierten LSM-Authentifizierung an. Für den Fernzugriff sollte man eine authentifizierte HTTPS-Verbindung verwenden. Die Chat- und Kontrollseiten haben dieselbe Herkunft.

## 3. Modellkanal hinzufügen

Öffnen Sie den Modellwahl- und Kanalverwaltungsbereich. Fügen Sie einen API-Kanal hinzu oder verbinden Sie ein unterstütztes Konto. Für einen typischen OpenAI-kompatiblen Endpunkt geben Sie einen Kanalnamen ein, wählen „Chat Completions“ aus, geben die Basis-URL der API sowie die Zugangsdaten ein. Sie können auch Modelle manuell auswählen oder eine bekannte Modell-ID angeben. Speichern Sie die Konfiguration und wählen Sie anschließend ein Modell aus.

Für einen lokalen Inferenzdienst sollte man eine Adresse verwenden, die vom Controller aus erreichbar ist – und nicht nur über den Browser. Beispielsweise ist `http://127.0.0.1:8080/v1` eine geeignete Adresse, wenn der Inferenzdienst auf dieser Adresse im Netzwerkbereich des Controllers läuft. Weitere Informationen zu Protokollen, Autorisierung von Accounts, Entdeckung von Modellen sowie Beschränkungen bezüglich des Kontextes finden Sie in [Channels and models](../chat/channels.md).

## 4. Eine erste Aufgabe ausführen

Starten Sie eine Konversation und stellen Sie ein einfaches Problem zur Verfügung, um die Verbindung des Modells zu testen. Versuchen Sie anschließend, einen Tool-Request mit nur Leserechten durchzuführen.

```text
Zählen Sie die Dateien im Wurzelverzeichnis des Controller-Workspaces auf.
Sagen Sie mir, welche Maschinen Sie überprüft haben – und fassen Sie die Ergebnisse zusammen.
Verändern Sie die Dateien nicht und führen Sie keine Schreibvorgänge durch.
```

Prüfen Sie das tatsächliche Ergebnis des Tools. Falls ein Tool fehlt, überprüfen Sie die Einstellungen bezüglich der Tools im Chat, die Einstellungen des Agents sowie die Berechtigungen der Maschine. Verwenden Sie für wiederkehrende Aufgaben einen gespeicherten Agenten und konfigurieren Sie dessen Zugriffsrechte entsprechend. Siehe dazu [Tools und Berechtigungen](../chat/permissions.md).

![WebUI-Chat mit einer Demonstrationskonversation](../assets/chat/chat-workspace.png)

Die Screenshots in diesem Handbuch sowie auf den folgenden Seiten wurden in einem isolierten Controller mit einem Demonstrationsmodell aufgenommen. Dabei wurden keine Produktionsdaten oder Gespräche berücksichtigt. Die englischen Benutzeroberflächen-Bezeichnungen können sich von den in der gewählten Sprache verwendeten Bezeichnungen unterscheiden.

## 5. Arbeitsbereich erkunden

| Ort/Region | Wofür kann man es verwenden? |
|---|---|
| Chats und Projekte | Starten und suchen von Chats, organisieren von Projekten, Verwendung von Tags sowie Markierungen für Nachrichten |
| Agents | Wiederverwendbare Modelle, Anweisungen und Werkzeugkonfigurationen |
| Erinnerung und Fähigkeiten | Verwaltung wiederverwendbaren Wissens und Anweisungen |
| Geplante Chats | Führen Sie einen gespeicherten Agenten mit einem wiederkehrenden Prompt aus. |
| Dateien und Terminals | Überprüfen oder bearbeiten der Controller- und Arbeitsumgebungen |
| Desktop-Bereich | Überprüfen und steuern unterstützte Fernverbindungen über GUI-Systeme |
| Sitzungen, Aufgaben und Überprüfungen | Überprüfung der dauerhaften Aufgaben, des Fortschritts bei der Ausführung sowie der Aktivitäten der Tools. |
| Maschinen und externe MCPs | Verwalten von Arbeitern sowie in sich verwobenen MCP-Servern |

Die genaue Auswahl der Kontrollmechanismen hängt von Ihrer Bereitstellung, Ihren Konten und den eingeschalteten Funktionen ab. Das Schließen des Browsers beendet nicht automatisch die Arbeit auf der Serverseite – verwenden Sie daher den „Stop“-Befehl, wenn Sie die Arbeit unterbrechen müssen.

## Nächste Schritte…

Lesen Sie den [WebUI Chat-Leitfaden](../chat/index.md), um den vollständigen Ablauf zu erfahren. Weitere Informationen zur Produktionsumgebung, zum Backup und zur Fehlerbehebung finden Sie in [Administration und Fehlerbehebung](../chat/administration.md).
