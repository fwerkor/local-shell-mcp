<!-- i18n-source-sha256: e5ebd5f8cfb42332f4e38d63eabe47a6274ceacf919130202203bd85917f3469 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Tools, Maschinen und Berechtigungen

## Autorisierungsschichten

Die aufgeführten Tools garantieren nicht unbedingt die Berechtigung, sie auszuführen. Die effektive Autorisierung setzt zusammen die Einschränkungen des Controllers, die Berechtigungen des authentifizierten Benutzers, die Maschinenrichtlinien, die Fähigkeiten des Agents sowie die Zustimmung der betreffenden Tools voraus. Einfache Anweisungen allein reichen nicht aus, um den Zugriff zu ermöglichen.

Registrierte Maschinen – einschließlich der lokalen Controller-Zielmaschine, wenn diese aktiviert ist – haben standardmäßig die Möglichkeit, in die Chat-Maschine zu schreiben bzw. Daten zu lesen. Bei sensiblen Umgebungen sollten diese Standardeinstellungen jedoch eingeschränkt werden. Unbekannte Maschinennamen erhalten keine automatischen Berechtigungen. Der Controller kann die lokale Ausführung oder die Fernausführung der Arbeiten unabhängig voneinander deaktivieren.

## Zugang zum Gerät

| Zugang | Bedeutung |
|---|---|
| Keine | Die Maschinenfunktionen sind nicht verfügbar. |
| Nur lesen | Es sind nur Operationen erlaubt, die als „nur zur Lesung“ klassifiziert werden. Eine beliebige Ausführung in Shell oder Python ist keine Operation, die nur zur Lesung steht. |
| Lesen/schreiben | Erlaubt autorisierte Lesefunktionen sowie Modifizierungs- und Ausführungsoperationen. Unterliegt jedoch anderen Beschränkungen. |
| Erben | Verwenden Sie den für den jeweiligen Fall geltenden Standardwert – anstatt einen expliziten Überrider. |

![Machinenberechtigungen und Genehmigungsmodus in einer Konversation](../assets/chat/machine-permissions.png)

Globale Vorgaben, Projektüberschreibungen und Überschreibungen pro Chat werden in den Maschinenberechtigungen eingestellt. Die Einstellungen eines Chats haben Vorrang vor denen des Projekts, diese wiederum vor den globalen Vorgaben. Ein Agent kann den Zugriff pro Maschine oder durch seine Standardrichtlinie weiter einschränken. Explizite Agent-Berechtigungen umgehen weder die Beschränkungen der authentifizierten Identität noch die des Controllers.

Beispiel: Bei globalem Lese-/Schreibzugriff, einer Projekteinstellung „Nur lesen“ und einem Agent mit Lese-/Schreibzugriff bleibt der Chat im Projekt auf Lesezugriff beschränkt, sofern seine eigene Richtlinie dies nicht ausdrücklich überschreibt. Auch eine Lese-/Schreibfreigabe im Chat kann eine Nur-Lesen-Grenze des Agents nicht überschreiten.

Eine geplante Ausführung mit einem benannten Agent verwendet die Maschinenrichtlinien dieses Agents sowie die gespeicherten Ausführungsbereiche. Dabei werden keine gewöhnlichen Chat-Maschinarien übernommen. Siehe dazu [Ziele und Automatisierung](automation.md). Verwenden Sie einen speziell für unbeaufsichtigte Aufgaben vorgesehenen Agent.

## Tool-Zulassung

| Stil/Moda | Verhalten |
|---|---|
| Automatisch | Autorisierte Tool-Aufrufe werden ohne eine zusätzliche Genehmigung durchgeführt – es sei denn, eine separate, ausdrückliche Richtlinie verlangt das Gegenteil. |
| Überprüfen Sie riskante Vorgänge | Der Verantwortliche bittet um eine Überprüfung der Operationen, die als gefährlich eingestuft werden können. Dazu gehören auch willkürliche Shell-Befehle sowie zahlreiche externe Anrufe. |
| Überprüfen Sie alle Tools | Es wird eine Genehmigung für die Anwendung von Standardwerkzeugen erfordert. |

Die Genehmigungseinstellungen eines Chats können die Vorgaben des Agents und die globalen Vorgaben erben. Bestehende ausdrückliche Ablehnungs- oder Genehmigungsregeln bleiben wirksam. Ein untergeordneter Agent kann den Genehmigungsmodus seines übergeordneten Agents nicht abschwächen. Genehmigungen sind von Berechtigungen unabhängig: Die Genehmigung einer verweigerten Maschinenaktion gewährt keinen Maschinenzugriff.

Überprüfen Sie die tatsächlichen Argumente, das Ziel sowie die möglichen Nebenwirkungen vor der Genehmigung. Bei einem unbeaufsichtigten Workflow sollten Sie die Agenten und die Genehmigungsrichtlinien sorgfältig festlegen. Eine Genehmigung durch einen Menschen kann den Fortschritt verlangsamen. Erweitern Sie den Zugriff nicht nur, um die Anweisungen zu beseitigen.

## Native und externe MCP-Werkzeuge

Die native Tools funktionieren mit dem Controller sowie den registrierten Arbeitsstationen über LSM. Das Tool-Register umfasst verschiedene Funktionen wie Dateioperationen, Shell- und Job-Funktionen, Browser- und GUI-Bedienungen, Fernwartung, logische Sitzungen sowie weitere Funktionen. Für genaue Angabepattern siehe [Tools-reference](../reference/tools.md). Für die Verbindung mit den Maschinen siehe [Remote-workers](../guides/remote-workers.md).

Verwalten von ineinander verwobenen MCP-Servern im WebUI. Unterstützte Konfigurationen umfassen lokale STDIO- und remote HTTP-Übertragungswege. Es können auch server-spezifische Umgebungsvariablen oder -Header verwendet werden. Die externe MCP-Funktion kann in der Chat-Bereichsleiste sowie im entsprechenden Agent aktiviert werden. Der Agent kann verfügbare externe Tools entdecken, überprüfen und nutzen. Die Autorisierung sowie die Genehmigung der Tools bleiben weiterhin gültig.

Ein externes MCP-Tool kann unabhängig von den nativen Maschinen-ACLs arbeiten: Eine externe Remote-API kann Ressourcen auch dann verändern, wenn lokaler Maschinenzugriff deaktiviert ist. Prüfen Sie die Berechtigungen und Zugangsdaten des externen Dienstes separat. Installieren Sie keine nicht vertrauenswürdigen stdio-Server auf einem Controller mit sensiblen Dateien.

## Fragen an den Benutzer sowie an die Aktivitäten/Features

„Ask User“ ermöglicht es einem Agenten, strukturierte menschliche Eingaben zu erhalten – anstatt einfach etwas zu erraten. Die Antwort wird durch die angegebene Frage gesteuert. Es handelt sich dabei um einen Antrag auf Informationen, nicht um eine Genehmigung, um eine verweigerte Anfrage zu umgehen. Wenn die Aufgabe unbeaufsichtigt bleibt, muss dem Agenten angeordnet werden, wie er mit Unsicherheiten umgehen soll und welche Interaktionen noch abgewartet werden müssen, bevor man annimmt, dass die Aufgabe abgeschlossen ist.

Der Komponist stellt verschiedene Funktionen zur Verfügung, wie zum Beispiel die Netzwerksuche, externe MCPs sowie Speichermöglichkeiten. Diese Funktionen bestimmen, welche Fähigkeiten dem Modell zur Verfügung stehen. Sie sind von der Autorisierung getrennt – das Deaktivieren einer Funktion führt nicht dazu, dass die historischen Ergebnisse gelöscht werden. Die Netzwerksuche ist standardmäßig aktiviert und verwendet nur lesbare Web-Tools, wie in [Netzwerksuche](../guides/webui-network-search.md) beschrieben.

## Aufsicht und Überprüfung

Prüfen Sie die Aufrufe der Tools sowie deren Ergebnisse im Chat. Erweitern Sie die Details, wenn Sie Fehler diagnostizieren. Die Controller-Audit-Log-Dateien dokumentieren die Aktivitäten der Tools. Die ausgeführten Aufgaben und Sitzungen zeigen an, wie die Arbeit abläuft. Ein erfolgreicher API-Antwort bedeutet nur, dass das Tool ein Ergebnis zurückgegeben hat – es bedeutet jedoch nicht unbedingt, dass die angeforderte externe Aktion ihren Zweck erreicht hat. Überprüfen Sie die Einträge, den Status der entfernten Aufgaben sowie den Zustand der Bereitstellung unabhängig voneinander. Weitere Informationen finden Sie in [Audit-Log](../guides/audit-log.md).
