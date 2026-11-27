<!-- i18n-source-sha256: 8ec601aa8e9c57afef769d8346567626355ccf88e122e3296735b7af3639c562 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat

LSM WebUI Chat ist ein selbsthostierter AI-Agentenbereich, der im Controller integriert ist. Sie können Ihren eigenen Modellendpunkt verwenden oder eine unterstützte Kontoverbindung nutzen. Dadurch erhält das Modell Zugang zu Ihren eigenen Tools und Maschinen. Es ist nicht notwendig, externe MCP-Clienten zu verwenden. Externe Clients können dennoch weiterhin direkt mit demselben Controller verbunden werden.

## Wie die einzelnen Teile zusammengefügt werden können

- **Controller:** Die Python-Service, die die Browser-Anwendung hostet, die Anfragen bearbeitet, die Tools ausführt, die Scheduling-Funktionen übernimmt sowie den persistierenden Zustand der Anwendung speichert.
- **Kanal:** Eine Modell-API-Verbindung oder eine unterstützte Kontoautorisierung – mit eigenen Zugangsdaten, Protokollen, einer Liste der Modelle sowie entsprechenden Einstellungen.
- **Modell:** Ein Identifikationswert für ein Modell innerhalb eines Kanals. Der gleiche Identifikationswert auf zwei Kanälen bedeutet nicht, dass es sich um denselben Endpunkt handelt.
- **Agent:** Eine wiederverwendbare Konfiguration, die aus einem Modell, Anweisungen, Werkzeugen, Fähigkeiten und Berechtigungen besteht.
- **Konversation:** gespeicherte Nachrichten, Einstellungen, Ausführungshistorie sowie die Verbindung zwischen dem Modell bzw. dem Agenten und den gespeicherten Daten.
- **Projekt:** Eine Gruppe von Gesprächen mit gemeinsamen Standardwerten.
- **Worker**: Ein ausgehendes Ausführungsziel. Es handelt sich dabei weder um einen Modellanbieter noch um einen separaten Chatserver.
- **Logische Sitzung:** Eine dauerhafte Identität der Aufgaben auf der Toolseite – unterschiedlich von einer Konversations-ID. Ein Chat kann diese Logische Sitzung nutzen, um Ziele, Fortschritte und die Arbeit mit dem Tool zu verfolgen.

Die Model-API erhält den kontext, der für das Modell sichtbar ist, sowie die Ergebnisse der Tools. Der Controller führt die autorisierten Tools aus. Das Modell verbindet sich nicht direkt mit einem Worker oder erhält seine eigene API-Schlüsselwörter. Der Browser stellt die Konversation dar und steuert den Controller.

## Wählen Sie einen Führer aus.

| Ich möchte… | Lesen |
|---|---|
| Installieren, sich anmelden und eine erste Aufgabe ausführen. | [Schnellstart](../getting-started/web-workspace.md) |
| Eine Model-API oder ein Konto anlegen. | [Kanäle und Modelle](channels.md) |
| Wiederverwendbare Agenten erstellen und Aufgaben delegieren. | [Agenten und Fähigkeiten](agents.md) |
| Chats, Dateien und Projekte verwalten. | [Konversationen](conversations.md) |
| Die Historie sowie die Kontextinformationen verstehen. | [Erinnerungen und Kontexte](context.md) |
| Die Ausführung einschränken und MCP-Werkzeuge verwalten. | [Werkzeuge und Berechtigungen](permissions.md) |
| Long-zeitige Aufgaben und Sitzungen ausführen. | [Ziele und Automatisierung](automation.md) |
| Die Webseite durchsuchen und Dokumente lesen. | [Netzwerk-Suche](../guides/webui-network-search.md) |
| Eine Bereitstellung administrieren, eine Sicherungskopie erstellen und Fehler beheben. | [Administration und Fehlerbehebung](administration.md) |

## Grundlagen.

Beginnen Sie mit einer eher begrenzten Anfrage – nur zur Lesereihe. Überprüfen Sie die Ausgaben des Tools, bevor Sie Änderungen vornehmen. Ein Modell kann falsch sein, auch wenn das Tool erfolgreich ist. Modelle für Zugangsdaten, Chat-Daten, Zugriff auf Maschinen sowie Genehmigungen durch das Tool sind unterschiedliche Aspekte. Die Änderung eines dieser Aspekte bedeutet nicht automatisch, dass der andere Aspekt ebenfalls korrekt ist. Insbesondere sollte ein öffentlicher Chat-Punkt als Sicherheitskontrollfläche geschützt werden.

Für den externen MCP-Client-Path siehe [Konnektivität des Clients](../clients/connectivity.md). Für die Argumente der Tools siehe [Referenz zu Tools](../reference/tools.md).
