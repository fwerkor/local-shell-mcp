<!-- i18n-source-sha256: 78ec7a5b5dc75473db69b12cf1626f81c3071f52661bf1023047af5d6d24e3ee -->
# Websuche und Dokumentenlesen in WebUI

Im WebUI-Chat ist die Websuche standardmäßig
aktiviert. Über den Schalter unter dem
Eingabefeld kann sie für einzelne
Unterhaltungen ausgeschaltet werden. Die
Einstellung wird je Unterhaltung gespeichert.
Weder ein Anbieter-API-Schlüssel noch
Shell-Berechtigungen für Worker sind
erforderlich.

Der Agent erhält nur zwei schreibgeschützte
Werkzeuge. `web_search(query)` liefert Titel,
URLs und Auszüge aus öffentlichen
Suchergebnissen. Es nutzt `ddgs`, falls
installiert, und andernfalls Bing RSS ohne
Schlüssel. Öffentliche Dienste können
Anfragen begrenzen oder ausfallen.

`web_fetch(url, query?, offset?, limit?)`
liest HTML, Klartext, JSON, XML, Markdown und
PDF. Bei arXiv-Zusammenfassungen wird nach
Möglichkeit die HTML-Volltextversion
geöffnet, sonst die PDF-Datei. Eine eigene
wissenschaftliche Such-API ist nicht nötig.

Beim ersten Abruf wird der vollständige Text
im privaten Controller-Cache gespeichert,
sofern das Verzeichnis beschreibbar ist. Der
Cache ist benutzergebunden, läuft nach 24
Stunden ab und enthält höchstens 80 Dateien
pro Benutzer. Die Antwort umfasst bis zu 8000
Zeichen; mit Suchbegriff, Offset und Limit
können weitere Abschnitte bis zu 12000
Zeichen pro Aufruf gelesen werden.

Downloads sind auf 20 MiB und extrahierter
Text auf 3 MiB begrenzt. Private Netzwerke,
Zugangsdaten in URLs, ungewöhnliche Ports und
unsichere Weiterleitungen werden blockiert.
Verbindungen nutzen ausschließlich geprüfte
öffentliche IP-Adressen, um DNS-Rebinding zu
verhindern.

PDFs werden mit PyMuPDF oder ersatzweise
`pypdf` verarbeitet. Scans ohne Textebene
benötigen OCR und führen zu einer klaren
Fehlermeldung. HTML wird anhand der
angegebenen Zeichencodierung gelesen;
unbekannte Formate werden abgelehnt.

Suchlinks erscheinen in der
Werkzeug-Ergebniskarte. Antworten sollten
möglichst die Original-URL und
PDF-Seitenzahlen nennen. Externe Inhalte
gelten als nicht vertrauenswürdig und dürfen
Anweisungen des Nutzers oder die
Agent-Konfiguration nicht überschreiben.
