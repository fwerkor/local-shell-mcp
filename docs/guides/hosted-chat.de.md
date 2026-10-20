<!-- i18n-source-sha256: f2dd1c4fffcc9783c739a12868fbcfa0023e0e3a783c8ba929f84107e3959e9a -->
# Gehosteter Chat (optional)

Hosted Chat ist ein selbst gehosteter BYOK-Chat und ein MCP Apps-Client, der in die Benutzeroberfläche von LSM integriert ist. Es handelt sich **nicht** um einen logischen Sitzungsmodus: Konversationen haben unabhängige Identitäten und können optional eine vorhandene logische LSM-Sitzung anhängen. ChatGPT und andere externe Clients arbeiten weiterhin mit denselben LSM-Sitzungen und Tools.

## Aktivieren

Der gehostete Chat ist standardmäßig deaktiviert. Set:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Starten Sie den Controller neu und öffnen Sie **Hosted Chat** direkt unter der Web-UI-/TUI-Auswahl. Die Funktion verfügt auch über einen mobilen Eintrag in der oberen Leiste. Der Chat-Host verwendet die vorhandene LSM-OAuth-Identität und -Bereiche. Derselbe Controller betreibt den MCP-Server, der von der Werkzeugschleife des Modells verwendet wird. Arbeiter können die Hinrichtung nicht veranlassen.

## Modellprofile

Wählen Sie **Modellprofile**, um ein Profil mit einem Namen, einer HTTPS-OpenAI-kompatiblen API-Basis-URL, einer Modell-ID und einem optionalen API-Schlüssel zu erstellen/bearbeiten. Mehrere Profile können nebeneinander existieren und Gespräche können das Modell wechseln.

Profile, Konversationen, der vollständige Nachrichtenverlauf und Tool-Aufrufergebnisse werden über das konfigurierte LSM-Status-Backend **auf dem Server gespeichert**. Ihr Umfang ist an den authentifizierten Prinzipal gebunden. Der API-Schlüssel wird mit AES-GCM verschlüsselt und niemals von Profillisten- oder Profildetail-Endpunkten zurückgegeben. Es wird nicht im Browserspeicher gespeichert, nicht als Eingabeaufforderung an das Modell gesendet oder in Prüfprotokolle aufgenommen. Der Chat-Host leitet es nur an die ausgewählte Modell-API weiter.

Die erste dateigestützte Bereitstellung erstellt `hosted-chat-encryption-key` im Statusverzeichnis mit Modus 0600. **Sichern Sie diese Datei zusammen mit den Statusdaten. Ohne sie können gespeicherte API-Schlüssel nicht entschlüsselt werden.** Wenn der Controller Redis, mehrere Replikate oder ein anderes Backend ohne Dateistatus verwendet, konfigurieren Sie einen stabilen, gemeinsam genutzten 32-Byte-URL-safe-base64-Schlüssel:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

Drehen Sie diese Einstellung nicht, ohne die verschlüsselten Profile zu migrieren. Verwenden Sie keine In-Memory-Statusspeicherung, wenn dauerhafte Gespräche erforderlich sind.

Standardmäßig werden nur Endpunkte des HTTPS-Modells mit DNS-Hostnamen akzeptiert. Lokale/private Endpunkte und HTTP werden abgelehnt, um das Risiko serverseitiger Anforderungsfälschungen zu verringern. Administratoren, die bewusst ein vertrauenswürdiges privates Modell-Gateway hosten, können sich für Folgendes entscheiden:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

Aktivieren Sie dies nicht auf einem nicht vertrauenswürdigen Mehrbenutzer-Controller, es sei denn, Benutzer sind berechtigt, interne Dienste zu kontaktieren.

## Gespräche und MCP-Apps

Erstellen Sie eine Konversation mit einem gespeicherten Modellprofil. Jeder eingereichte Zug wird zu einer servereigenen Hintergrundaufgabe; Durch Schließen des Browsers wird die Aufgabe nicht abgebrochen. Abgeschlossene Text- und Werkzeugaufrufe werden zwischen Modell-/Werkzeugschritten dauerhaft mit Prüfpunkten versehen. Stoppen Sie explizit, um zu unterbrechen. Beim Neustart des Controllers werden unterbrochene Läufe als solche markiert und können in einer neuen Runde fortgesetzt werden, aber **Werkzeugaufrufe mit unbekanntem Ergebnis werden nie automatisch wiederholt**.

Der gesamte Nachrichtenverlauf der Konversation bleibt im Speicher erhalten. Nur ein begrenztes aktuelles Fenster wird gleichzeitig an das Modell gesendet, um die Kontextgröße zu steuern. Tool-Aufrufe werden über den authentifizierten MCP-Endpunkt von LSM gesendet, wobei alle normalen Tool-Berechtigungen und das Audit-/Preflight-Verhalten erhalten bleiben.

Öffnen Sie **Live Workspace**, um die vorhandene `workspace_open` MCP Apps-Ressource von LSM in einer eingebetteten Ansicht darzustellen. Der Host verwendet die `@modelcontextprotocol/ext-apps`-Brücke für den App-Lebenszyklus, die Erneuerung von Anmeldeinformationen, Toolaufrufe und Aktionen zwischen Mensch und Agent. Es ist kein zweiter Dateimanager, Terminal, Audit oder Job-UI implementiert.

Mit dem optional angehängten `session_id` kann Hosted Chat eine vorhandene logische Sitzung verwenden und anzeigen. Dadurch wird die Sitzung nicht neu klassifiziert und Hosted Chat wird nicht zum Eigentum daran erklärt. Chat-Konversations-IDs und logische Sitzungs-IDs sind getrennt.

## Grenzen

- Modellanfragen verwenden OpenAI-kompatible Chat-Vervollständigungen mit Tool-Aufrufen; Für andere Anbieterprotokolle ist ein Adapter erforderlich.
- Schutzmaßnahmen pro Runde begrenzen Modelliterationen und Werkzeugaufrufe. Längere Aufgaben können mithilfe der dauerhaften Historie in einer neuen Runde fortgesetzt werden.
- Das Löschen von Chat-Konversationen ist explizit. Es wird keine automatische Verlaufslöschung durchgeführt.
- Der Controller muss über seinen eigenen MCP-Client im Netzwerk erreichbar sein und der Browser muss für die LSM Live Workspace API autorisiert sein.
