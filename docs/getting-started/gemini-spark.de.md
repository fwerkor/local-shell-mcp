<!-- i18n-source-sha256: 0d50677fe8bd21dbf6f3fff366adea800f15d50fdbc67ed3b77abf84437f73eb -->
# Gemini Task / benutzerdefinierte Apps verbinden

Mit der **benutzerdefinierten verbundenen Apps**-Funktion von Gemini kann ein berechtigter Gemini-Benutzer eine Verbindung zu einem Remote-MCP-Server herstellen. LSM kann den MCP-Endpunkt bereitstellen. Dies ist eine **alternative Client-Verbindung** zu [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) und anderen MCP-Clients; Es ersetzt oder implementiert den LSM-Controller nicht.

Google beschränkt benutzerdefinierte Apps derzeit auf **Benutzer ab 18 Jahren in den USA**, die mit einem **persönlichen Google-Konto** angemeldet sind und **Aktivität beibehalten** aktiviert haben. Die Funktion ist auf **Englisch** verfügbar. Verbindungen müssen in der Gemini-Web-App erstellt werden, verbundene Apps können jedoch später auf Mobilgeräten verwendet werden. Verfügbarkeit und UI-Beschriftungen können sich ändern; konsultieren Sie den [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

## Vor dem Anschließen

- Starten Sie eine LSM-Laufzeit, beispielsweise mit [Docker Compose](../installation/docker.md), und überprüfen Sie deren Zustand.
- Stellen Sie den MCP-Endpunkt über **öffentlich erreichbares HTTPS** bereit und lassen Sie OAuth aktiviert.
- Kennen Sie die Authentifizierungsdetails des Controllers und genehmigen Sie nur die Bereiche, die Sie benötigen.
- Verwenden Sie einen begrenzten Arbeitsbereich oder Container. Zwillinge können Vorgänge mit echten Auswirkungen auf Dateien, Maschinen und Terminals anfordern.

Der in Gemini einzugebende Endpunkt ist:

```text
https://your-public-host.example.com/mcp
```

Geben Sie die Web-Benutzeroberfläche (`/ui`), die LibreChat-URL oder den Website-Ursprung nicht ohne `/mcp` ein. Öffentliche Bereitstellungen sollten die Authentifizierung nicht deaktivieren, um Verbindungsfehler zu umgehen.

## Verbinde dich mit Zwillingen

1. Öffnen Sie auf einem Computer [Gemini](https://gemini.google.com/) und melden Sie sich mit einem berechtigten persönlichen Konto an.
2. Öffnen Sie **Einstellungen & Hilfe → Verbundene Apps**. Abhängig von der aktuellen Schnittstelle befindet es sich möglicherweise unter **Personal Intelligence → Verbundene Apps**.
3. Wählen Sie unter **Benutzerdefinierte Apps** die Option **Benutzerdefinierte App hinzufügen** aus oder verwenden Sie das URL-Feld für die benutzerdefinierte App.
4. Fügen Sie die LSM-HTTPS-`/mcp`-URL ein und wählen Sie dann **Weiter**.
5. Vervollständigen Sie den OAuth- und Einwilligungsfluss mit dem LSM-Controller. LSM unterstützt die OAuth-Erkennung und die dynamische Client-Registrierung. Wenn Gemini stattdessen manuelle OAuth-Client-Anmeldeinformationen anfordert, überprüfen Sie die erweiterten Optionen und Ihr LSM-OAuth-Setup, bevor Sie fortfahren.
6. Geben Sie in einer Gemini-Konversation `@` ein und wählen Sie die verbundene benutzerdefinierte App aus, um ein LSM-Tool anzufordern.

Beginnen Sie mit: „Verwenden Sie die verbundene LSM-App, um die Umgebung zu überprüfen und Arbeitsbereichsdateien aufzulisten. Ändern Sie nichts.“ Überprüfen Sie die Tool-Ergebnisse und die Controller-Prüfung, bevor Sie Schreibvorgänge versuchen.

## Task-Modus (früher Spark) verwenden

Für mehrstufige Entwicklung, Fehlersuche und Serverwartung empfiehlt sich **Task** statt normalem Chat: Aufgaben lassen sich planen, verbundene Werkzeuge wiederholt nutzen und Fortschritte verfolgen. Dies ist eine Workflow-Empfehlung, keine gemessene Geschwindigkeits- oder Qualitätsgarantie.

Wählen Sie auf der Gemini-Startseite unter dem Eingabefeld **Task** und schließen Sie gegebenenfalls die Einrichtung ab. Geben Sie `@` ein, wählen Sie LSM, falls angeboten, und nennen Sie Ziel, Zielmaschine oder Arbeitsbereich sowie Abschlusskriterien.

Beispiel: „Untersuche mit LSM das Repository, reproduziere den fehlgeschlagenen Test, behebe die Ursache und führe die Tests erneut aus. Berichte über geänderte Dateien und Ergebnisse.“

Verfolgen Sie den Fortschritt und bestätigen Sie nötige Aktionen. Prüfen Sie LSM-Aufrufe im Auditprotokoll des Controllers: Geminis eigener Cloud-Computer ist nicht Ihr LSM-Arbeitsbereich. Halten Sie Controller und benötigte Worker online. Task und benutzerdefinierte Apps haben unterschiedliche Voraussetzungen; siehe [offizielle Task-Anleitung](https://support.google.com/gemini/answer/17094507), falls eine Option fehlt.

## Grenzen und Fehlerbehebung

- **Keine Option für benutzerdefinierte Apps:** Bestätigen Sie Konto, Region, Alter, Sprache und Berechtigung zum Speichern von Aktivitäten. Hierbei handelt es sich um eine Gemini-seitige Verfügbarkeitseinschränkung und nicht um einen LSM-Konfigurationsfehler.
- **URL wird abgelehnt:** Verwenden Sie einen extern erreichbaren HTTPS-Endpunkt `/mcp`. Überprüfen Sie die OAuth-Erkennung und Ihren Reverse-Proxy.
- **OAuth schlägt fehl:** Überprüfen Sie den LSM-Autorisierungsbildschirm, die Client-Registrierung, die Rückruf-URL und die gewährten Bereiche. Veröffentlichen Sie keinen nicht authentifizierten MCP-Endpunkt.
- **Ein Tool fehlt oder schlägt fehl:** Die clientseitige MCP-Tool-/Schema-Unterstützung kann unterschiedlich sein. Versuchen Sie es mit einem einfachen schreibgeschützten Aufruf und überprüfen Sie die LSM-Prüfung und -Protokolle. Die vollständige Kompatibilität mit allen Funktionen des Gemini-Clients kann nicht garantiert werden.
- **Trennen:** Gehen Sie zurück zu **Verbundene Apps**, um LSM zu deaktivieren, die Verknüpfung aufzuheben oder zu entfernen, wenn es nicht mehr benötigt wird.

Googles [official guide](https://support.google.com/gemini/answer/17209137) beschreibt den neuesten Ablauf und die Verfügbarkeit benutzerdefinierter Apps. Informationen zu einer lokalen CLI-basierten Gemini-Integration finden Sie stattdessen unter [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). Das LSM [ChatGPT connector tutorial](chatgpt-connector.md) bleibt unabhängig verfügbar.
