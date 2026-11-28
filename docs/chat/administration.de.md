<!-- i18n-source-sha256: 91fa7e8e41354be2761864ffe05d1efb85063953c79a40065ad61661cc15b836 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Verwaltung und Fehlerbehebung

## Bereitstellungsarchitektur

Das WebUI-Frontend wird vom Python-Controller aus bereitgestellt – und zwar im selben Ort wie seine REST- und MCP-Endpunkte. Der Standard-Backend ist SQLite. Die veröffentlichten Binärdateien sowie die Wheels enthalten die kompilierten Frontend-Dateien. Für die Erstellung des Frontends aus Quellcode ist das JavaScript-Build-Toolkit erforderlich – es muss nicht der installierte Controller betrieben werden. Node.js, MongoDB, Meilisearch sowie ein separat bereitgestellter LibreChat-Backend sind nicht erforderlich.

Nutzen Sie die [Quickstart-Unterstützung](../getting-started/quickstart.md) sowie die [Konfigurationsreferenz](../reference/configuration.md). Für die Herstellung von Source-Code besuchen Sie bitte die [WebUI-Build-Anleitung](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## Sichern Sie die Bereitstellung des Systems.

Verwenden Sie einen vertrauenswürlichen HTTPS-Reverse-Proxy oder Tunnel. Achten Sie auf Authentifizierung und die Verwendung sicherer Passwörter. Bewahren Sie den Controller innerhalb eines geeigneten Containers oder einer virtuellen Maschine auf. Beschränken Sie den Zugriff von außen und schützen Sie die ausgehenden Daten. Exponieren Sie keine unautorisierte Ausführungspunkte im öffentlichen Internet.

Ein Proxy muss in der Lage sein, Antworten ohne Buffering zu übertragen und auch WebSocket-Übernahmen für Anwendungen unterstützen. Verwenden Sie angemessene Timeout-Werte für lange Anfragen sowie die zulässigen Übertragungsgrößen. Halten Sie die konfigurierte öffentliche URL-Konfiguration mit der Origin-URL des Browsers sowie den OAuth-Antworten übereinstimmend. Beheben Sie TLS-Fehler nicht durch globale Deaktivierung von Zertifizierungsprüfungen.

Die Anfragen werden vom Controller aus gestellt. Die für das Modell sichtbaren Nachrichten, Anhänge sowie Ergebnisse der Tools können an die ausgewählte API gesendet werden. Überprüfen Sie die Bedingungen bezüglich der Verarbeitung von Daten vor dem Einsatz vertraulicher Inhalte. Schützen Sie auch die externen MCP-Geheimnisse sowie die Token der Arbeiter.

## Zustand, Backup und Upgrades

Der Standard-Ordner für die Daten ist `.local-shell-mcp`, der sich im konfigurierten Arbeitsbereich befindet. Der Wert von `LOCAL_SHELL_MCP_STATE_DIR` kann diesen Ordner ändern. Die gemeinsam genutzte Datenbank heißt `lsm.sqlite3`. Chats, Projekte, Einstellungen, Agenten, Speicherplatz, Zeitpläne sowie der Ausführungsstatus werden auf dem Server gespeichert. Anhänge, Arbeitsbereichsfiles und andere Dateien können hingegen außerhalb der Datenbank gespeichert werden.

Erstellen Sie eine vollständige Kopie des Zustandsverzeichnisses, sowie eine Konfiguration außerhalb dieses Verzeichnisses. Ebenso sollten die entsprechenden Dateien des Bereitstellungsumfelds sowie der entsprechenden Arbeitsbereiche ebenfalls kopiert werden. Betrachten Sie die Backups als sensible Daten. Ein Backup, das nur die Datenbank enthält, kann möglicherweise nicht alle Anhangsdateien oder Konfigurationsdaten enthalten. Verwenden Sie daher einen Controller, der in einem stabilen Zustand ist, oder ein konsistentes Backup-Methodik für SQLite. Die Kopie des HauptSQLite-Databasis allein kann möglicherweise den bereits abgelegten WAL-Inhalt nicht enthalten. Überprüfen Sie die Backups, indem Sie sie wiederherstellen auf einem isolierten Testumgebungsbereich.

Bevor eine Aktualisierung durchgeführt wird, sollten Sie die aktuelle Version, den Laufzeitpfad, die Konfiguration, die Standort der aktiven Aufgaben sowie alle relevanten Daten aufzeichnen. Beenden Sie anschließend die laufenden Prozesse oder leeren Sie diese sicher ab. Erst danach sollten Sie eine Sicherungskopie erstellen und die Installation aktualisieren. Überprüfen Sie außerdem die Authentifizierung, den Chatverlauf, die Modellgenerierung, das Streaming sowie die geplanten Aufgaben. Die Migration von SQLite-Dateien aus der alten Version wird beim Start unterstützt. Bewahren Sie die alten Dateien weiterhin auf, bis Sie die Migration erfolgreich abgeschlossen haben. Verwenden Sie nicht eine leere Testdatei anstelle der produktiven Datenordner.

Ein Rollback bedeutet nicht einfach, den Binärdateinamen zu ändern – schließlich hat eine Datenbank-Migration den persistierenden Zustand verändert. Es ist notwendig, den kompatiblen Zustand wiederherzustellen, und es sollte vermieden werden, zwei unabhängig konfigurierte Controller auf demselben Speicher zu nutzen.

## Fehler bei der Diagnose des fehlgeschlagenen Chats.

| Symptome. | Überprüfen zuerst. |
|---|---|
| Die UI kann nicht geladen werden. | Verarbeitung durch den Controller, Frontend-Bundle, korrekte URL-Adresse, Proxy und Authentifizierung |
| Das Modell fehlt. | Kanalkonfiguration, Modell-Erkennung, Modell-ID, Accountautorisierung. |
| HTTP 401/403 von dem Anbieter. | API-Schlüssel/Account, Berechtigungen des Anbieters, ausgewählter Kanal und Protokoll. |
| HTTP 429 | Upstream-Raten/Quotenbegrenzungen, gleichzeitige Anfragen, Status des Accounts/Plans. |
| HTTP 400/413/422 | Kompatibilität der Anfragen, Größe der Eingaben/Kontext, Begrenzungen bezüglich Anhänge, Modellparameter. |
| HTTP-5xx-Fehler oder Zeitüberschreitung | Gesundheit des Anbieters, Netzwerkverbindungen, Leistungsfähigkeit der Server, Proxy-Zeitüberschreitungen |
| Die Ausgabe hört auf zu streamen | Wiederherstellung/Neuinstallation des Systems; Überprüfung des Status der Generierung sowie der detaillierten Fehlerinformationen |
| Das Tool ist nicht verfügbar | Funktionstasten, Fähigkeiten der Agenten, Maschinen-ACL, OAuth-Berechtigungen, Controller-Schalter |
| Arbeiter sind offline. | Arbeiterregistrierung, Ausgangskonnektion, Heartbeat sowie Controller-Protokolle |
| Es gibt noch Genehmigungen/Anfragen, die abgewickelt werden müssen | Die Gesprächsverbindung wird geöffnet und die angeforderte Aktion wird überprüft |
| Die Terminplanung läuft nicht | Eingeschaltete Zustand, Zeitzone, Agent/Channel, Ziel, gespeicherte Autorisierungen, letzte Ausführung |

Glauben Sie nicht, dass alle HTTP-Fehler von derselben Servicequelle stammen. Unterscheiden Sie zwischen einem Fehler beim Anmelden über LSM, einem Fehler in der API des Upstream-Modells, einem externen MCP-Fehler und einem Fehler im Transportprozess des Workers. Überprüfen Sie die detaillierten Fehlermeldungen sowie die relevanten Controller-Protokolle. Entschlüsseln Sie die Schlüsselwerte, Bearer-Token sowie die Callback-URLs vor der Weitergabe dieser Informationen.

## Wiederholungsversuche und Wiederherstellungsmaßnahmen des Providers

Vor Beginn einer Modellantwort können vorübergehende Verbindungsfehler und bestimmte HTTP-Fehler (408, 429, 500, 502, 503, 504) mit begrenzter Wartezeit erneut versucht werden. Die derzeitigen normalen Wartezeiten betragen 1, 2, 4, 8, 16, 30, 30 und 30 Sekunden (acht Wiederholungen nach der ersten Anfrage). HTTP Retry-After kann eine Wartezeit auf bis zu 120 Sekunden verlängern; bestimmte Streaming-Fehler führen zu zufälligen Abweichungen. Das Wiederholungslimit gilt pro Modellanfrage und nicht für die gesamte Lebensdauer des Chats. Die Kontextkomprimierung hat einen eigenen Wiederherstellungspfad. Ein Rate-Limit wegen aufgebrauchten Guthabens kann bestehen bleiben, bis der Anbieter das Kontingent erneuert. Automatische Wiederholungen garantieren keinen Erfolg und machen ein Abonnement nicht unbegrenzt.

Eine Unterbrechung während des Prozesses unterscheidet sich von einem Fehler, der vor dem ersten Antwortantrag auftritt. Verlassen Sie sich nicht auf die automatische Wiederholung einer teilweise ausgeführten Aktion. Überprüfen Sie den gespeicherten Status sowie den externen Zustand, bevor Sie weitere Versuche unternehmen. Falls der Prozess noch läuft, verbinden Sie sich erneut anstatt eine duplizierte Arbeit zu starten. Falls der Prozess fehlschlägt, verwenden Sie die entsprechenden Wiederherstellungsmöglichkeiten oder starten Sie einen neuen Prozess, falls der ursprüngliche Prozess nicht weiterlaufen kann.

Fehler bei der Kompression des Kontexts sollten getrennt von normalen Fehlern bei der Erstellung von Modellen untersucht werden. Überprüfen Sie die effektive Kontextgrenze, die Kompatibilität der Modelle, die übermäßig großen Ergebnisse der Tools sowie den verfügbaren Quoten. Siehe [Memory and context](context.md).

## Was sollte in einem Fehlerbericht eingefügt werden?

Berichten Sie über die Version/Lösung des LSM, die Installationsmethode, das Betriebssystem, den Protokolldienst, den Typ des gesicherten Endpunkts, die ID des Modells, die ungefähre Zeit, in der der Fehler auftritt, die Schritte zur Wiederherstellung des Systems, den aktuellen Zustand der Chats/Prozesse sowie alle relevanten Fehlermeldungen. Bei einem Problem am Remote-System sollten Sie auch die Version des Workern, den Namen des Rechners sowie den Status von Heartbeat/Poll-Funktionen angeben. Gegebenenfalls sollten Sie auch eine kleine Demonstration des Problems erstellen. Senden Sie niemals API-Schlüssel, OAuth-Token, private Informationen oder andere unnötige persönliche Daten.
