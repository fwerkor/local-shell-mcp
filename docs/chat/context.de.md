<!-- i18n-source-sha256: 214687d6067b7dc2dd2b6eec1a207aa50be3ab9550d081f8a60e3013684c0250 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Speicher, Kontext und die Verwendung von Tokens

## Drei verschiedene Arten von Staaten

| Staat | Zweck |
|---|---|
| Konversationen/ Gesprächsverläufe | Die ursprünglichen Nachrichten sowie die Aktivitäten der Tools werden vom Kontrolleur gespeichert. |
| Kontextfenster | Die Teilmenge der Anweisungen, Tool-Schemata, historische Daten, Zusammenfassungen sowie andere Daten, die bei einer bestimmten Modellanfrage gesendet werden. |
| Dauerhafte Erinnerung | Wiederverwendbare Fakten und Präferenzen, die über verschiedene Gespräche hinweg in dem entsprechenden Gedächtnisbereich zugänglich sind. |

Eine lange gespeicherte Unterhaltung kann die Grenzen des Kontextfensters des Modells überschreiten, ohne dass die gesamte Geschichte der Unterhaltungen verloren geht. Das bedeutet nicht, dass die gesamte Akteuhistorie bei jedem Modellanruf übermittelt wird.

## Verwaltung der Speicherkapazität

![Seitenleiste zur Speicherverwaltung mit einem Beispieleintrag](../assets/chat/memory-management.png)

Die Speicherfunktion ist standardmäßig aktiviert – es sei denn, sie wurde vom Benutzer deaktiviert, durch die Einstellungen des Chats oder aufgrund von Beschränkungen bezüglich der Funktionalitäten des Agents. Nutzen Sie die Seite zur Verwaltung des Speichers, um gespeicherte Daten zu überprüfen und zu bearbeiten. Bitten Sie den Agenten, nützliche Informationen, Projektkonventionen oder Präferenzen zu speichern. Überprüfen Sie anschließend das Ergebnis im Speicherinterface.

Beim Bearbeiten einer Speicherposition sollte man verwenden, wenn möglich, eine Taste, die nur Kleinbuchstaben und Unterstrich enthält. Beispiel: `repository_conventions`Der Standardwert für die Länge der Einträge beträgt 10.000 Zeichen. Eine Installation kann die Speichergrenzen selbst festlegen. Wenn ein Eintrag abgewiesen wird, sollte man den Fehler genauer untersuchen – anstatt die Geheimnisse auf verschiedene Schlüssel zu verteilen.

Die Speicherung von Daten kann entweder über einen gemeinsamen Speicherpool oder über einen speziellen Bereich für jeden Agenten erfolgen – abhängig von der Konfiguration des Agents. Bitte speichern Sie keine API-Schlüssel, Passwörter oder andere sensiblen Daten in der Speicherung. Die Deaktivierung des Speichers verhindert die Verwendung dieser Daten im entsprechenden Bereich. Dies ist nicht dasselbe wie das Löschen bestehender gespeicherter Daten oder das Entfernen von Informationen aus dem Gesprächsverlauf.

Wenn die Daten angezeigt werden, verwendet das Modell die Funktion `set_memory`, um Einträge zu erstellen oder zu aktualisieren. Ein leeres Wertfeld löscht den entsprechenden Eintrag wieder. Die Funktion `find_memory` sucht nach Einträgen anhand von Abfragen oder genau definierten Schlüsseln. Eine leere Abfrage listet alle gespeicherten Daten auf. Der optionale Flag `include_conversations` ermöglicht es, auch Texte aus anderen Gesprächen zu berücksichtigen. Die Seitenzuweisung erfolgt über die Parameter `page` (Standardwert: 1) und `limit` (Standardwert: 10, maximal: 50). Bei der Auswahl der Daten wird der Text des Gesprächs berücksichtigt, nicht die Aufrufe der Tools. Die Auswahl der Daten erfolgt nach Relevanz – daher sollten Sie genaue Bezeichnungen oder Begriffe verwenden und bei Bedarf die Abfrage anpassen.

Die automatische Eingabe von Informationen in das Gedächtnis bleibt während der verschiedenen Gesprächsszenen stabil. Dadurch können die bereits eingesetzten Präfixe für die Anweisungen wieder verwendet werden. Die Bearbeitung des gespeicherten Gedächtnisses führt nicht dazu, dass die bereits eingesetzten Daten rückwirkend überschrieben werden. Die explizite Abfrage der gespeicherten Daten ermöglicht es, neue Informationen einzubauen, falls dies notwendig ist.

## Kontextfähigkeit

Setzen Sie den tatsächlichen Kontextbegrenzungen jedes Modells in dessen Kanal fest. Der Controller schätzt die für das Modell sichtbare Eingabe und reserviert dabei Platz für die Ausgabe. Die aktuelle Budgetumsetzung setzt einen Kompaktorat von 85% sowie eine Reserverate von 5% voraus. Diese Werte können je nach der tatsächlichen Konfiguration des Modells und der Laufzeitvariablen abweichen. Die Ergebnisse können bei unbekannten Tokenisatoren, multimodalen Anfragen oder spezifischen Schemata des Anbieters etwas ungenau sein.

Die Kontextkomposition kann sowohl Systemanweisungen, Agentkonfigurationen, Werkzeugdefinitionen, Anhänge, vorherige Nachrichten sowie Ergebnisse der Tools umfassen. Ein Anbieter kann einen anderen Tokenizer verwenden oder zusätzliche internale Tokens berücksichtigen. Betrachten Sie die Anzeige als operativen Leitfaden – nicht als eine Garantie seitens des Anbieters.

## Automatische Kompaktierung

Wenn ein Kontextbudget eine Kompaktion erfordert, erstellt der Controller einen Überblick über den alten Kontext. Dabei werden alle relevanten Informationen erfasst – einschließlich der Ziele, Einschränkungen, Entscheidungen, Fortschritte sowie der relevanten Identifikatoren und Ergebnisse der Tools. Die ursprünglich gespeicherten Daten bleiben weiterhin verfügbar für weitere Überprüfungen. Der Überblick ist jedoch eine von dem Modell erstellte Annäherung an die ursprünglichen Daten – keine perfekte Wiedergabe.

Die Komprimierung erfolgt vor dem nächsten Anforderungsvorgang – dabei wird der Kontext reduziert. Falls die Zusammenfassung fehlschlägt, versucht das System erneut, entsprechend seiner Fehlerbehandlungsmechanismen weiterzumachen. Es sollte nicht einfach mit einer bereits übermäßig großen Eingabedatei weitergemacht werden. Überprüfen Sie den Zustand der Komprimierung sowie eventuelle Fehler. Die aktuellen Nachrichten sowie die Beziehungen zwischen den Werkzeugen und den Ergebnissen müssen weiterhin konsistent bleiben. Erledigte Ergebnisse sollten nicht einfach wiederholt in den Kontext eingefügt werden, um den Kontext zu verringern.

Eine einzige, sehr große Eingabedatei oder ein Werkzeugergebnis kann den festgelegten Budgetrahmen übersteigen. Bitte fordern Sie eine begrenzte Ausgabe, Dateien oder eine Zusammenfassung an. Große Ergebnisse sollten in Dateien gespeichert werden, damit sie nicht immer wieder in den Kontext eingefügt werden müssen.

## Kumulative Nutzung und Cache-Ergebnisse

Die Anzeige der Sitzungsnutzung sowie die Kontextfenster beantworten unterschiedliche Fragen. Die Eingabe-/Ausgabe-Nutzung sammelt sich über alle Anforderungen hinweg an – einschließlich wiederholter Kontexte. Die Cache-Metriken beschreiben die vom Anbieter gemeldeten Ergebnisse, die im Cache gespeichert sind. Die Kontextfüllung misst die aktive Kapazität des Modells und zählt nicht alle vorherigen Anforderungen zusammen.

Beispielsweise verbraucht eine Anforderung mit 20.000 Eingabestoken sowie eine weitere Anforderung mit 25.000 Eingabestoken insgesamt 45.000 Eingabestoken. Die zweite Anforderung verwendet jedoch nur etwa 25.000 Eingabestoken aus dem aktuellen Kontext. Gespeicherte Token sind nicht kostenlos, es sei denn, der Anbieter legt es anders fest. Eine höhere Kontextkapazität ändert die Kapazität des Modells – nicht jedoch die bereits verbrauchte Nutzung.

Die Komprimierung kann die aktuelle Belegung reduzieren, während gleichzeitig die Verbrauchswerte des Modells erhöht werden. Die Änderung der Modelle bewirkt eine Veränderung der anwendbaren Grenzen; dabei werden die früheren Verbrauchswerte nicht gelöscht. Wenn ein Anbieter die genauen Nutzungsdaten oder die Cache-Metadata weglässt, können die Schätzungen und Metriken unvollständig sein. Für die finanzielle Abrechnung sollten Sie die Rechnungsdaten und Preise des Anbieters verwenden – nicht nur die Informationen, die in der LSM-Anzeige angezeigt werden.

## Kosten reduzieren und wichtige Informationen bewahren.

Behalten Sie die stabilen Anweisungen bei. Vermeiden Sie unnötig große Ausgaben von Werkzeugen und nutzen Sie eine gezielte Suche. Führen Sie eine separate Konversation für unverbindliche Aufgaben durch. Wenn eine Übergabe notwendig ist, speichern Sie einen prägnanten Checkpoint mit genauen Pfaden, Commit-IDs, beobachteten Ergebnissen sowie offenen Fragen. Überprüfen Sie wichtige Fakten anhand der ursprünglichen Quelle oder der Ergebnisse des Werkzeugs – anstatt sich ausschließlich auf eine generierte Zusammenfassung zu verlassen.
