<!-- i18n-source-sha256: 012f0d9f7b350fcf47e3fd6afdf2fc9e7044ff28cb2eca7c029c3d6af35f3b04 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Gespräche und Projekte

## Einen Chat erstellen und fortführen.

Öffnen Sie eine neue Konversation, wählen Sie einen Kanal/Modell oder einen Agent aus und geben Sie eine Nachricht ein. Das Chatfenster wird auf dem Controller abgewickelt und die Aktualisierungen werden in den Browser übertragen. Das Laden der Seite neu oder das Schließen einer Registerkarte bedeutet nicht, dass die Ausführung abgebrochen wird. Verwenden Sie den „Stopp“-Modus, um eine Ausführung zu unterbrechen und den aktuellen Zustand überprüfen können, bevor Sie eine weitere Aktion starten.

Eine gespeicherte Chatsitzung behält ihre Verbindung zum entsprechenden Modell bzw. Agenten bei. Sie können diese Verbindung absichtlich ändern, wenn Sie ein anderes Modell verwenden möchten. Eine Konversation ist keine logische Sitzung – sie enthält Nachrichten von Benutzern sowie Nachrichten des jeweiligen Modells. Eine logische Sitzung hingegen enthält die Aufgaben, den Fortschritt und den Plan bezüglich der Arbeit mit dem Tool. Behalten Sie die relevanten IDs bei, wenn Sie eine lange Aufgabe weitergeben müssen.

## Arbeit organisieren und finden.

Verwenden Sie Projekte, um verwandte Gespräche zu gruppieren und festzulegen, welche Berechtigungen für die gemeinsame Nutzung des Geräts gelten sollen. Ein Projekt kann mehrere separate Chats enthalten. Bewegen oder erstellen Sie die Chats in das entsprechende Projekt – anstatt davon auszugehen, dass alle separaten Gespräche denselben Kontext haben. Das aktive Projekt kann dem Agenten Informationen über die Organisation des Gesprächs geben.

Tags kategorisieren die Gespräche. Nachrichten werden durch Markierungen angezeigt, wodurch man auf bestimmte Nachrichten zugreifen kann und auch wieder zu nützlichen Ergebnissen gelangen kann. Das ist etwas anderes als das Hinzufügen von Gesprächsseiten zum Menü. Verwenden Sie Titel der Chats, Suchfunktionen sowie Anzeigen für ungelöste Nachrichten, um eine übersichtliche Seitenleiste zu erhalten.

Das Archivieren bedeutet, dass eine Konversation aus der normalen Liste entfernt wird – ohne dass die gespeicherten Informationen gelöscht werden. Eine Konversation kann wieder aus dem Archiv wiederhergestellt werden, wenn dies notwendig ist. Das Löschen einer Konversation ist jedoch zerstörerisch; verwenden Sie das Löschen daher nicht als Ersatz für das Archivieren. Die aktuelle Implementierung nutzt den SQLite-Status der Konversationen. Nehmen Sie nicht an, dass es noch die alte, komprimierte Form des Hosted Chat-Archivs gibt.

## Nachrichtenoperationen und laufende Aufgaben

Verfügbare Befehle hängen von der jeweiligen Nachricht sowie deren aktuellem Ausführungszustand ab. Wenn nötig, kann man eine bestimmte Aktion wiederholen oder eine ausgewählte Aktion löschen, wenn sie nicht mehr benötigt wird. Die Löschung ändert den gespeicherten Kontext der Gespräche – dies kann Auswirkungen auf spätere Situationen haben. Es ist jedoch nicht möglich, Shell-Befehle, Remote-Aktivitäten, Git-Übertragungen oder andere externe Effekte rückgängig zu machen.

Bei der Wiederholung einer fehlgeschlagenen Aktion sollten zunächst die detaillierten Fehleranalysen gelesen werden sowie die bereits abgeschlossenen Aktionen überprüft werden. Falls eine Aktion vor dem Abbrüchen erfolgreich verlaufen sein könnte, sollte der externen Zustand noch einmal überprüft werden. Falls weitere Nachrichten in der Warteschlange liegen oder eine Aktion bereits läuft, sollten die angezeigten Kontrollen und Statusinformationen berücksichtigt werden – anstatt davon auszugehen, dass mehrere Aktionen gleichzeitig in demselben Chat ablaufen. Das Panel für die in der Warteschlange liegenden Nachrichten ermöglicht es, die noch ausstehenden Aktionen zu überprüfen. Die Steuerung versucht, nach Abschluss der aktuell ausgeführten Aktionen eine angemessene Anleitung zu geben. Keine dieser Operationen kann die Effekte der bereits abgeschlossenen Aktionen rückgängig machen.

## Anhänge, Vorschauen und andere Dokumente/Objekte

Verwenden Sie die Funktion zum Hochladen von Dateien oder unterstützten Bildern. Die Implementierung des Hochladens beschränkt die Größe der einzelnen Anhänge auf 32 MiB. Zudem können durch die Anforderungen bezüglich der Bereitstellung/Proxy-Anfragen noch kleinere Grenzen festgelegt werden. Die hochgeladenen Dateien werden auf dem Controller gespeichert und können vom Modell abgerufen werden. Die Interpretation von Bildern erfordert ein Modell sowie einen Provider, der Bilder akzeptiert. Das Hochladen von Dateien bedeutet nicht, dass man Zugriff auf lokale oder entfernte Dateien hat.

Bei der Anforderung eines generierten Dateispecifiziert man den gewünschten Pfad, das Format sowie den Inhalt der Datei. Stellen Sie sicher, dass die erzeugte Datei tatsächlich existiert, bevor Sie sie weiterempfehlen. Laden Sie die unterstützten Anhänge und Dateien herunter oder überprüfen Sie deren Inhalt. Eine generierte Datei kann an den Controller übertragen werden – oder es kann ein entsprechender Dateielink verwendet werden. Siehe [Dateielinks](../guides/file-links.md).

Die Darstellung von Artefakten kann dazu führen, dass React, HTML, SVG, Markdown und Mermaid in einem separaten Panel angezeigt werden – anstatt nur als Code dargestellt zu werden. In den Einstellungen der Agent-Artefakte verwendet „Normal“ die standardisierten Anweisungen. „shadcn/ui“ fügt Hinweise zur Verwendung von Komponenten und Bibliotheken hinzu. „Custom“ hingegen sorgt dafür, dass die Darstellung der Artefakte ohne die integrierten Anweisungen möglich ist. Den generierten Code sowie den dargestellten Inhalt sollten man als unzuverlässig betrachten. Überprüfen Sie diese vor dem Einsatz außerhalb des Vorherschaubereichs. Die Dateien, die für die Office-Anzeige verwendet werden, sind getrennt von den generierten UI-Artefakten.

Fügen Sie keine Zugangsdaten, privaten Schlüsseln oder Dokumente hinzu, die Sie nicht berechtigt sind, an den ausgewählten Modellanbieter zu senden. Die Löschung von Anhängen und Chats ist getrennt von der Löschung der Quelldateien auf dem Computer.

## Präferenzen

Chat- und Benutzervorlieben wie die Aktivierung von Funktionen sowie Tastaturshortcuts werden über die WebUI verwaltet und auf dem Server gespeichert, an dem diese Funktionen implementiert sind. In den Einstellungen können die Tastaturverhalten konfiguriert werden. Es ist wichtig zu unterscheiden zwischen dem Senden einer Nachricht und der Eingabe eines Zeilenumbruchs. Die Aktivierung der Chat-Funktionen sollte getrennt von den Berechtigungen des Agents konfiguriert werden. Weitere Informationen finden Sie in [Funktionen und Berechtigungen](permissions.md) sowie [Speicher und Kontext](context.md).
