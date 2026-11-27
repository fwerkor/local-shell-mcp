<!-- i18n-source-sha256: 01c14c19cf5addf99299993b57542259bcb40bbfb13600758b516a86c89e716b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Ziele, geplante Gespräche sowie langfristige Aufgaben

## Wählen Sie das richtige Verfahren aus.

| Mechanismus | Zweck |
|---|---|
| Einfache Chats erzeugen | Antworten auf die aktuellen Anweisungen – einschließlich des Aufrufs von Tools |
| Chat-Ziele festlegen | Eine aktive, logische Sitzung über die Grenzen der Modellwürfe hinweg fortsetzen |
| Geplante Chats | Starten Sie einen Agent mit einer gespeicherten Anweisung, der regelmäßig ausgeführt wird. |
| Perpetuierte Aufgaben oder Terminals | Befehle ausführen, unabhängig von einer einzelnen Modellanweisung |
| Unteragenten | Eine begrenzte Aufgabe an einen anderen Agent-Thread delegieren. |

Eine geplante Chat-Sitzung ist keine dauerhafte Shell-Job-Operation. Eine logische Sitzung ist auch keine Konversation oder ein Prozess des Betriebssystems. Das Abbrechen einer solchen Sitzung bedeutet nicht unbedingt, dass alles, was mit den dazugehörigen Tools begonnen wurde, abgebrochen wird.

## Chat-Ziele festlegen

Für eine langwierige Aufgabe sollte man dem Agenten auftragen, ein konkretes Ziel zu definieren und einen Plan zu erstellen, wobei dabei die Logical Session-Tools verwendet werden. Der Plan enthält alle Schritte sowie deren Status. Die Chat-Betriebssituation kann einen aktiven Plan auch bei Übergängen zwischen Modellen fortsetzen – ohne dass auf eine Anweisung des neuen Benutzers oder auf den Inaktivitätstimer des externen MCP Live-Workspaces gewartet werden muss.

Prüfen Sie den Plan und den Fortschritt. Wenn nötig, können Sie die Fortsetzung des Plans stoppen, wieder aufnehmen oder den Plan ganz absagen. Die Fortsetzung ist nur möglich, wenn der Plan noch aktiv ist und es sich um einen gültigen Plan handelt. Ein bereits abgeschlossener, blockierter oder abgebrochener Plan kann nicht weiter fortgesetzt werden. Wiederholte, identische Antworten ohne Fortschritt führen dazu, dass der Prozess pausiert wird – anstatt in einen endlosen Zyklus zu geraten (derzeit nach drei unveränderten Grenzen). Lösen Sie das eigentliche Hindernis vor der Wiederaufnahme des Plans.

Definieren Sie die Kriterien für die Erledigung der Aufgaben. Zum Beispiel: Überprüfen Sie den Repository-Status, implementieren Sie die notwendigen Änderungen, führen Sie die entsprechenden Tests durch und melden Sie eventuelle Fehler. Bitten Sie den Agenten, genaue Commit-IDs sowie Testergebnisse zu dokumentieren – anstatt nur aufgrund eigener Pläne eine erfolgreiche Ausführung der Aufgaben anzunehmen.

Das externe Zielmechanismus des MCP-Klients ist getrennt voneinander. Weitere Informationen zum Workflow der Übertragung von Logical Sessions und Live-Workspaces finden Sie in [Human Interface](../guides/human-interface.md).

## Erstellen Sie einen geplanten Chat.

![Seitenleiste für geplante Chats mit einem deaktivierten Beispielzeitplan](../assets/chat/scheduled-chats.png)

Öffnen Sie die Funktion zur Verwaltung der geplanten Chats. Erstellen Sie eine Tagesplanung mit einem beschreibenden Namen, einer gespeicherten Agentin, einem Anweisungsfeld, der Zeitzone sowie der Frequenz der Chats. Wählen Sie anschließend das Ziel für die Chats aus – optional können Sie auch ein Projekt für einen neuen Chat auswählen. Speichern Sie die Tagesplanung und aktivieren Sie sie. Nutzen Sie die Möglichkeit zur manuellen Ausführung, um die Konfiguration vor der Verwendung zu überprüfen.

Die unterstützten Zeitpläne umfassen Stunden-, Tages- und Wochenabläufe sowie eine kontinuierliche Ausführung der Aufgaben. Die kontinuierliche Ausführung beginnt nach einer festgelegten Verzögerung. Eine Verzögerung von null Minuten kann dazu führen, dass der Prozessor und die Maschine weiterhin mit hoher Leistung arbeiten. Übliche wiederkehrende Zeitpläne setzen eine Mindestabstände von fünf Minuten voraus. Verwenden Sie dazu einen expliziten IANA-Zeitzone-Code. `Asia/Shanghai` Oder `UTC`Überprüfen Sie anschließend die angezeigten Daten des nächsten Laufes nach dem Speichern.

Ein cron-Beispiel für 09:00 Uhr an Werktagen:

```text
0 9 * * 1-5
```

Dabei wird die ausgewählte Zeitzone verwendet – nicht unbedingt die Zeitzone des Controllers. Überprüfen Sie außerdem, ob die ausgewählte Zeitzone die entsprechenden Zeitzonenwechsel berücksichtigt.

## Zielgruppen des Gesprächs

- **Bei jedem Lauf neuer Chat:** Es ist sinnvoll, für jede Erkundigung einen separaten Chat zu starten. Dadurch können die Berichte unabhängig voneinander erstellt werden.
- **Denselben Chat wiederverwenden:** Es kann eine Konversation erstmals erstellt werden und anschließend bei weiteren Ereignissen wieder verwendet werden. Dies ist besonders nützlich für die kontinuierliche Überwachung von Prozessen.
- **Bestehenden Chat verwenden:** Wählen Sie einen bereits bestehenden Chat aus, bei dem die Teilnehmer in regelmäßigen Abständen miteinander kommunizieren können.

Eine wiederverwendete oder bereits existierende Unterhaltung kann weiterhin wachsen – allerdings kann es notwendig sein, diese Unterhaltungen zu komprimieren. Wählen Sie unabhängige Chats, wenn der historische Kontext nicht mehr relevant ist. Die geplante Ausführung hängt von dem ausgewählten Agenten sowie dem noch verfügbaren Modellkanal ab.

## Unbeaufsichtigte Berechtigungen

Die geplante Ausführung gehört dem Controller und verwendet gespeicherte Namen autorisierter Scopes statt eines dauerhaft gespeicherten Browser-Anmeldetokens. Speichern oder starten Sie einen Zeitplan bei Bedarf manuell, um ihn zu autorisieren. Die Maschinenberechtigungen des ausgewählten Agents gelten; normale Maschinenüberschreibungen des Projekts oder Chats sind nicht die Maschinenrichtlinie des Zeitplans. Controller-Beschränkungen, gespeicherte Autorisierung, Tool-Fähigkeiten und Tool-Genehmigungen gelten weiterhin.

Für externe MCP-Server mit Authentifizierung bedeutet eine interaktive Anmeldung nicht automatisch eine erneuerbare Berechtigung zur unbeaufsichtigten Ausführung. Meldet die Zeitplan-Oberfläche, dass eine erneute Authentifizierung oder unbeaufsichtigter Zugriff erforderlich ist, klären Sie die serverspezifischen Zugangsdaten oder entfernen Sie diese Abhängigkeit vor der Aktivierung. Verwenden Sie Browser-Tokens nicht als Ersatz.

Verwenden Sie einen nur zur Überwachung nutzbaren Agenten. Beschreiben Sie ausdrücklich die zulässigen Ziele, die gewünschten Ergebnisse sowie die Maßnahmen, die zu vermeiden sind. Wenn eine geplante Aufgabe menschliche Interventionen oder Genehmigungen erfordert, überprüfen Sie die laufenden Prozesse. Nehmen Sie nicht an, dass die unbearbeitete Ausführung der Aufgabe bedeutet, dass es keine Einschränkungen gibt. Ein Beispiel für eine Überwachungsanweisung:

```text
Überprüfen Sie die angegebene Trainingsaufgabe sowie die dazugehörigen Protokolle.
Berichten über den aktuellen Schritt, die Verluste, die Durchsatzrate, die voraussichtliche Ankunftszeit sowie eventuelle neue Fehler.
Verändern Sie die Dateien nicht, beenden Sie den Vorgang nicht und starten Sie auch keine neuen Aufgaben.
Falls die Daten nicht verfügbar sind, bitte angeben Sie den genauen Grund dafür.
```

## Lebenszyklus und Wiederherstellung

Der Controller behält die Terminpläne sowie die Ausführungszustände der Transaktionen bei. Dadurch werden Duplikationen der Ausführungen vermieden. Eine Browser-Tab ist nicht notwendigerweise weiterhin geöffnet zu halten. Man sollte nicht davon ausgehen, dass verpasste Ereignisse immer wieder durchgeführt werden oder dass alle externen Arbeiten auch nach einem Neustart des Controllers weiterhin bestehen bleiben. Es ist wichtig, die letzte Ausführung, die nächste Ausführung sowie die aktuell laufenden Transaktionen zu überprüfen – außerdem sollte man auch den Chatverlauf nach dem Ausfall überprüfen.

Deaktivieren Sie die Termine, um zukünftige automatische Vorgänge zu verhindern. Überprüfen Sie außerdem alle bereits laufenden Termine separat. Das Beenden der zukünftigen Terminplanungen bedeutet nicht unbedingt, dass die aktuelle Ausführung des Jobs abgesagt wird. Entfernen Sie die nicht mehr benötigten Terminpläne und widerrufen Sie die für den Agenten nicht mehr benötigten Berechtigungen.

Ein von einem WebUI-Agent erstellter Arbeitsauftrag oder Terminal kann auch nach dem Abschluss der normalen Modellantworten weiterhin existieren. Eine Neustart des Controllers allein reicht nicht aus, um diesen Arbeitsauftrag zu beenden. Eine explizite Abbrücheinheit, das Verlieren der Berechtigungen oder die Ablaufzeit der Berechtigungen können dazu führen, dass die von dem Agent erledigten Aufgaben annulliert werden. Wenn der Arbeiter nicht online ist, kann die Annullierung der Aufgabe bis zum Zeitpunkt des Lieferns der Aufgabe aufgeschoben bleiben. Überprüfen Sie den Arbeitsauftrag oder das Terminal selbst, bevor Sie annehmen, dass die Ausführung abgebrochen wurde. Der Agent kann seine eigenen Arbeitsaufträge nur über den gesicherten WebUI-Zugang senden oder stoppen. Externe MCP-Klienten behalten ihre eigene Semantik bei.

Die Werkzeuge und Aufgaben der Agenten haben jeweils ihren eigenen Lebenszyklus. Ein Ergebnis kann auch nach Abschluss der Ausführung noch nicht zur Verfügung gestellt werden. Überprüfen Sie daher den Bereich „Background-Tasks“ des Gesprächs und sammeln Sie das Ergebnis. Oder lassen Sie die vorgesehene Aktion auslösen, damit die zuständige Person wieder tätig werden kann. Führen Sie keine duplizierten Aufgaben durch – nur weil das Ergebnis noch nicht sichtbar ist.

Für Anweisungen, die über die Dauer eines einzelnen Tools hinausgehen sollen, sollten Sie die von LSM verwalteten Aufgaben oder persistente Terminals verwenden. Speichern Sie die Ausgaben in einer Protokolldatei, fügen Sie die Identifikatoren der Aufgaben hinzu und überprüfen Sie den tatsächlichen Fortschritt. Siehe dazu [Usage Patterns](../guides/usage-patterns.md).
