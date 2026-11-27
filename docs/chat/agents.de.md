<!-- i18n-source-sha256: d33afa60bf803b367c950dbadf80fa77167568a970adcac204cdea7e9e965e45 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Agenten und Fähigkeiten

## Wann sollte man einen Agenten erstellen?

Ein direkter Modellchat ist nützlich für einmalige Fragen oder Aufgaben. Ein „Agent“ ist eine gespeicherte Konfiguration, die wiederholt verwendet werden kann – entweder in abgestimmten Chats oder an andere Agenten weitergegeben werden kann. Unterschiedliche Agents können unterschiedliche Kanäle, Modelle, Anweisungen und Zugriffsrichtlinien nutzen. Sie teilen denselben Controller – aber nicht unbedingt denselben Speicherbereich oder Tools.

## Einen Agent konfigurieren

Verwalten Sie den Agenten über die WebUI. Erstellen Sie einen neuen Agenten, geben Sie ihm einen unverwechselbaren Namen und wählen Sie dessen Modell aus. Geben Sie außerdem Anweisungen an den Agenten ein – diese sollten die Aufgabe, das gewünschte Ergebnis, die Einschränkungen sowie die Anforderungen an die Überprüfung beschreiben. Konfigurieren Sie anschließend die notwendigen Fähigkeiten des Agents. Speichern Sie alles und starten Sie dann eine neue Konversation mit dem Agenten.

![Agent-Builder mit Anweisungen, Tools, Genehmigungen und Einstellungen der Skills](../assets/chat/agent-builder.png)

Zum Beispiel könnte ein Repositorie-Reviewer folgende Anweisungen haben:

```text
Überprüfen Sie die Änderungen im Vergleich zur aktuellen Hauptversion.
Überprüfen Sie das Repository sowie die Testergebnisse, bevor Sie Schlussfolgerungen ziehen.
Editieren Sie keine Dateien, senden Sie keine Commits aus oder führen Sie keine Änderungen durch.
Berichten Sie über konkrete Ergebnisse, zusammen mit den entsprechenden Pfaden und Beweisen.
```

Anweisungen sind nützlich, um das Verhalten der Maschine zu steuern – doch sie stellen keine Grenzen bezüglich der Berechtigungen dar. Die Zugriffsrechte der Maschine sollten auf „Leseberechtigung“ eingestellt werden. Unnötige externe Funktionen sollten ebenfalls weggelassen werden, falls der Revisor nichts ändern möchte. Weitere Informationen finden Sie in [Werkzeuge und Berechtigungen](permissions.md).

Es ist besser, für verschiedene Aufgaben unterschiedliche Agenten einzusetzen – beispielsweise für die Code-Überprüfung, die Implementierung sowie die Betriebsführung. Geben Sie jedem Agenten so wenig Zugriffsrechte wie möglich und wählen Sie ein Modell aus, das zu seiner Rolle passt. Falls ein Agent nicht starten kann, sollten Sie zunächst den verwendeten Kanal sowie das zugehörige Modell überprüfen, bevor Sie unnötige Änderungen vornehmen.

## Skills

Die Skill-Pakete enthalten wiederverwendbare Anleitungen sowie zugehörige Dateien. Diese werden üblicherweise mit einem bestimmten Symbol gekennzeichnet. `SKILL.md` Verwalten der Fähigkeiten im WebUI – Aktivieren der relevanten Fähigkeiten und stellen diese dem Agenten oder dem Chat zur Verfügung. Das Modell kann den Fähigkeitsinhalten bei Bedarf auf die entsprechenden Stellen zugreifen. Eine Fähigkeit kann beispielsweise einen Arbeitsablauf beschreiben, Beispiele angeben oder Skripte enthalten. Eine Fähigkeit führt jedoch nicht automatisch Skripte aus oder gewährt dem Agenten zusätzliche Berechtigungen.

Überprüfen Sie die importierten Fähigkeiten vor dem Aktivieren dieser. Behandeln Sie deren Anweisungen und Dateien wie jedes andere Third-Party-Code oder Prompt. Machen Sie die Namen und Beschreibungen der Fähigkeiten so spezifisch, dass das Modell sie leicht erkennen kann. Halten Sie große Referenzen getrennt und bevorzugen Sie kleine, eigenständig verwendbare Arbeitsabläufe. Die Registry auf der Controller-Seite sowie die Tool-Calls werden in [Skills](../guides/skills.md) beschrieben.

Die automatischen Fähigkeiten sowie der zugehörige Gedächtniskontext werden während eines Gesprächs aufgezeichnet. Dadurch wird vermieden, dass der Systembefehl bei jedem Spielzug neu eingesetzt werden muss. Änderungen bezüglich der Fähigkeiten können so direkt wirken. Bei der Tests der neu bearbeiteten automatischen Kontexte sollte man daher ein neues Gespräch starten. Eine absichtlich geladene Fähigkeit unterscheidet sich von dem ursprünglichen automatischen Kontext.

## Delegation und Unteragenten

Agenten können begrenzte Aufgaben an Subagenten delegieren, wenn dies möglich ist. Ein Kind kann einen konfigurierten Agenten verwenden und seine eigene, „Konversationen-artige“ Ausführung beibehalten. Der Elternagent koordiniert die Aufgabe, liest die Ergebnisse des Kindes und kann die gespeicherte Arbeitssequenz fortsetzen. Die Aktivitäten des Kindes können vom Elternagent aus überwacht werden. Diese Ansicht ist jedoch keine unabhängige, bearbeitbare Chat-Oberfläche.

Delegation sollte für trennbare Aufgaben verwendet werden – beispielsweise für unabhängige Überprüfungen, separate Dateien oder die Untersuchung verschiedener Hypothesen. Dem Kind sollte ein konkretes Ziel, ein definierter Umfang sowie eine erwartete Ergebnis angegeben werden. Gleichzeitige Schreibvorgänge auf denselben Dateien sollten vermieden werden, es sei denn, die Arbeit wird ausdrücklich koordiniert.

Die Delegation muss innerhalb der von dem Elternteil genehmigten Grenzen bleiben. Es wird keine Zugriffsmöglichkeit auf Maschinen oder MCP-Dienste gewährt, die vom Elternteil nicht verwendet werden können. Die Genehmigungsrichtlinien des Kindes dürfen die Richtlinien des Elternteils nicht beeinträchtigen. Kinderaufgaben können Model-Token sowie Zeit unabhängig nutzen. Deshalb sollten die Aktivitäten und Ergebnisse der Kinder bei der Bewertung von Kosten und Fortschritten überwacht werden.

## Werkzeuge, Aktionen und Artefakte

Der Agent Builder stellt seine verfügbare Werkzeugbibliothek sowie die Möglichkeiten der fortgeschrittenen Konfiguration zur Verfügung. Wählen Sie nur die Funktionen aus, die Sie benötigen. Für eine HTTP-Aktion, die durch ein OpenAPI-Schema beschrieben wird, sollten Sie die Endpunkte, die Authentifizierungsanforderungen sowie die zulässigen Operationen überprüfen, bevor Sie die Aktion verwenden. Eine Aktion kann eigene Authentifizierungsmechanismen haben. Eine Maschinenberechtigung stellt weder eine Autorisierung noch eine Entziehung von Drittanbieter-API-Zugangsdaten dar. Überprüfen Sie die Antwort der Aktion, bevor Sie eine Fernänderung als abgeschlossen betrachten.

Für generierten Benutzeroberflächen-Content muss die Darstellung des Contents wie in [Conversations and projects](conversations.md) beschrieben konfiguriert werden. Der generierte Code ist keine zuverlässige Erweiterung des Controllers.

## Praktische Vorlagen für Agenten

- **Leseberechtiger Ermittler:** Prüft die Protokolle und Quellen, vergleicht die Beweise, ermittelt die Ursachen – ohne dass Änderungen vorgenommen werden dürfen.
- **Implementierungsagent:** Editieren Sie das Repository, führen Sie gezielte Tests durch, berichten Sie über die Unterschiede sowie über noch nicht gelöste Fehler. Bei sensiblen Operationen ist eine Genehmigung erforderlich, wenn dies angemessen ist.
- **Monitoring-Agent:** Überprüft die ausgewählten Maschinen und berichtet über deren Status, Fehler sowie den gemessenen Fortschritt. Es wird keine Neustart der Arbeitsvorgänge durchgeführt, es sei denn, dies ist ausdrücklich erlaubt.
- **Forschungsagent:** ermöglicht die Suche in dem Netzwerk, die Zitation der Originaldokumente, die Unterscheidung zwischen Beweisen und Schlussfolgerungen. Außerdem werden Maschinenbearbeitungen nur dann eingesetzt, wenn dies notwendig ist.

Die Vorlagen dienen lediglich als Anleitungen – sie sind keine eingebauten Einstellungen. Sie müssen die tatsächlichen Berechtigungen und Fähigkeiten jedes Agents so konfiguriert werden, dass sie zu seiner vorgesehenen Aufgabe passen.
