<!-- i18n-source-sha256: 158a01475edc97cea1a70bc0d7b9a7330f7240dce14e7269635e675d044eedae -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Kanäle und Modelle

## Erstellen Sie einen Kanal.

Öffnen Sie den Modellauswahlmodus in Chat und gehen Sie zu „Kanalverwaltung“. Wählen Sie **Neuen Kanal hinzufügen**, wählen Sie den gewünschten Verbindungstyp aus, geben Sie die erforderlichen Informationen ein und speichern Sie das Ergebnis. Wählen Sie anschließend ein Modell aus diesem Kanal für eine neue Chatsitzung aus. Für einen benutzerdefinierten Agenten können Sie das Kanal- und Modellprofil in der Agentkonfiguration auswählen.

Die Kanäle werden von den Kontrolleuren verwaltet – nicht von den Nutzern selbst. Bei autorisierten Installationen erfordert die Verwaltung der Kanäle das Bereichsrecht `admin:config`. Ein Administrator kann gemeinsame Kanäle konfigurieren, ohne dabei API-Schlüssel an die Chat-Nutzer verteilen zu müssen.

![Fügen Sie ein Modellkanal in das Dialogfeld zur Konfiguration des eigentlichen Kanals hinzu.](../assets/chat/channel-settings.png)

Ein normaler API-Kanal hat einen Namen, das Verbindungsprotokoll, die Basiserweiterungsadresse, Anmeldeinformationen sowie Identifikatoren der Modelle. Verwenden Sie dazu die für den ausgewählten Endpunkt vergebenen API-Schlüssel – nicht die Passwörter Ihres LSM-Kontos. LSM sendet Anfragen vom Controller aus; eine URL, die auf Ihrem Laptop funktioniert, funktioniert möglicherweise nicht vom Controller aus.

| Protokoll | Beispiel für die Basis-URL der API | Verwenden |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | OpenAI-kompatible Chat-Gateways und lokale Inferenzserver |
| OpenAI Responses | `https://api.openai.com/v1` | Ein Gateway, das die Response-API zur Verfügung stellt. |
| Anthropischer Eingeborener | `https://api.anthropic.com/v1` | APIs, die mit anthropischen Botschaften kompatibel sind |
| Google Gemini-Native | `https://generativelanguage.googleapis.com/v1beta` | Gemini stellt APIs bereit, die mit den Content-Standards von Gemini kompatibel sind. |

Verwenden Sie die von dem Anbieter vorgegebenen Baseroutinen, anstatt eine vollständige Generierungsanfrage-URL einzugeben – eine URL, die auf einem Ende endet. `/chat/completions`Ein Gateway, das die Kompatibilität mit OpenAI anzeigt, könnte zwar Chat-Completions unterstützen – aber keine Antworten, keine Toolanrufe, keine Streaming-Funktionen, keine multimodalen Eingaben oder Rechenfunktionen. Wählen Sie daher das tatsächlich unterstützte Protokoll aus. Beispiel-URLs sind nur Beispiele für Protokolle – sie geben keine Garantie für kostenlose Zugangsmöglichkeiten oder Verfügbarkeit des Gateways.

## Lokale und benutzerdefinierte Endpunkte

Für einen Server, der mit OpenAI kompatibel ist und direkt am Controller angesprochen werden kann, könnte die Basiserweiterungsadresse `http://127.0.0.1:8080/v1` sein. Wenn der Server in Docker betrieben wird, bezieht sich „Loopback“ auf dieses Container-Netzwerk – nicht auf den physischen Host. Es sollte eine Adresse verwendet werden, die aus dem Netzwerkbereich des Controllers erreichbar ist. Die Registrierung eines entfernten Arbeiters allein macht die Inference-API nicht erreichbar.

Der Modell-URL-Validator erfordert die Verwendung von HTTPS – außer bei HTTP-Verbindungen zu Hosts, die in einer direkten Rückwärtslaufverbindung stehen.`localhost`, `127.0.0.1`, `::1`Ein HTTP-Endpunkt auf einer LAN-Adresse oder ein Docker-Dienstname muss über einen HTTPS-Gateway verfügbar gemacht werden. Die Funktion zur Umstellung des privaten Endpunkts für Hosted Chat ist nicht mehr verfügbar. Basen-URLs dürfen keine eingebetteten Zugangsdaten, Fragmente oder Abfragezeichen enthalten.

Verwenden Sie TLS für entfernte Endpunkte. Beschränken Sie den Zugriff auf vertrauenswürdige private Gateways. Überprüfen Sie außerdem die Model-Identifikatoren gegenüber dem Inferenzserver. Geben Sie die API-Schlüssel niemals in Form von Anweisungen, Screenshots, Abfragezeichen oder in der veröffentlichten Konfiguration ein. Lassen Sie den API-Schlüssel beim Bearbeiten eines bestehenden Kanals leer, um den gespeicherten Schlüssel zu bewahren. Verwenden Sie eine Schlüssellose Verbindung nur dann, wenn die Dienstleistung dies unterstützt.

## Umgebungsbedingte Standardwerte

Das integrierte OpenAI-Profil kann vor dem Start mit den Parametern `LOCAL_SHELL_MCP_MODEL_BASE_URL` (oder `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL` und `LOCAL_SHELL_MCP_MODEL_API_KEY` (oder `OPENAI_API_KEY`) konfiguriert werden. Die integrierten Anthropic- und Google-Profilen können die Parametre `ANTHROPIC_API_KEY` und `GOOGLE_KEY` bzw. `GOOGLE_API_KEY` nutzen. Die gespeicherten integrierten Profile haben Vorrang vor den von der Umgebung abgeleiteten Ersatzwerten. Verwenden Sie benannte Kanäle für mehrere unabhängige Endpunkte. Umgebungsbedingte Standardwerte sind keine Alternative zur Schutzmaßnahme gegen die Veröffentlichung von Dienstgeheimnissen.

## Autorisierung des ChatGPT-Kontos

Der Kanal „Account/Codex“ verwendet einen autorisierten Zugriff auf das ChatGPT-Konto, anstatt einen normalen API-Schlüssel. Beginnen Sie die Autorisierung über die Kanalverwaltung und loggen Sie sich auf der offiziellen Autorisierungsseite ein. Bei einer lokalen Implementierung kann die Autorisierung automatisch ablaufen. Wenn der Browser nicht auf den „Loopback-Listener“ zugreifen kann, kopieren Sie den gesamten Callback-URL-Code aus dem Adressfeld des Browsers und fügen Sie ihn in das Autorisierungsfenster ein. Bei diesem manuellen Prozess ist eine Verbindungsunterbrechung am „Loopback-Adresse“ zu erwarten.

Behandeln Sie die Callback-URL wie Zugangsdaten: Senden Sie sie niemals in einem Chat und veröffentlichen Sie sie nicht. Der Controller speichert die Autorisierung serverseitig und erneuert die Zugangsdaten, wenn möglich. Autorisieren Sie das Konto erneut, wenn es abläuft oder der Zugriff widerrufen wird. Verfügbare Modelle, Tarifgrenzen und zulässige Nutzung werden vom vorgelagerten Kontodienst festgelegt; LSM stellt kein zusätzliches Abonnementkontingent bereit.

## Entdeckung von Modellen und Kontextbegrenzungen

Ermöglichen Sie die automatische Erforschung, um Informationen über das Modell vom Anbieter zu erhalten. Der Controller aktualisiert diese Daten regelmäßig – derzeit alle zehn Minuten. Es ist auch möglich, die Daten manuell zu aktualisieren. Bei Fehlern bei der Erforschung werden die bisher gespeicherten Modelldaten beibehalten. Falls der Anbieter kein kompatibles Endpunkt für die Listung von Modellen hat, sollten Sie die Erforschung deaktivieren und die Modellidentifikatoren manuell eingeben – jeweils eine Identifikationsnummer pro Zeile.

Bestimmen Sie den Kontext für jedes Modell, sobald dieser bekannt ist. Eine explizit festgelegte Wertung übertrifft die ermittelten Metadaten oder ergänzt fehlende Werte. Der Editor kann 1 bis 2.000.000 Token verarbeiten. Dies ist jedoch nur eine Konfigurationsgrenze – es gibt keine Garantie dafür, dass der Anbieter diese Kapazität unterstützt. Verwenden Sie die für Ihre Implementierung geeignete Grenze, wobei Sie berücksichtigen sollten, dass sowohl die Serverseitige Konfiguration als auch die eigenen Grenzen des Modells eine Rolle spielen.

## Auswahl, Rechentätigkeit und Nutzung

Die Standardwerte für Kanäle und Modelle bestimmen, welche Anfragen vom ausgewählten Anbieter unterstützt werden. Der Chat-Compiler kann dabei die Rechenkosten berücksichtigen, sofern diese verfügbar sind. Unterschiedliche Protokolle implementieren die Auswahl und Rechentätigkeit auf unterschiedliche Weise. Eine Option könnte von einem bestimmten Modell nicht unterstützt werden. Beginnen Sie mit den Standardwerten des Anbieters, ändern Sie anschließend eine Einstellung nach der anderen.

LSM kann die genaue Nutzung der Streaming-Token anfordern – und in solchen Fällen auf alternative Lösungen zurückgreifen, wenn der Anbieter die Nutzung der Token ausdrücklich ablehnt. Ein Endpunkt, der keine Informationen zur Nutzung der Ressourcen zurückgibt, kann keine genauen Abrechnungsdaten oder Statistiken über den Speicherverbrauch liefern. Weitere Informationen dazu finden Sie in [Memory and context](context.md). Dort wird unterschieden zwischen dem kumulierten Verbrauch und der aktuellen Kapazität des Speichers.

## Änderungen und Löschung von Kanälen

Eine Unterhaltung behält weiterhin das ausgewählte Modell bzw. den Agenten sowie die dazugehörige Historie bei. Das Modell muss absichtlich gewechselt werden, wenn es um die Änderung der Endpunkte oder die Behebung von Problemen mit dem Dienstgeber geht. Die Umbenennung eines aktuell genutzten Kanals ist aufgrund der Schutzmaßnahmen gegen Verwechslungen nur in bestimmten Fällen möglich. Die Löschung eines aktuell genutzten Kanals erfordert eine zusätzliche Bestätigung: Die Historie bleibt erhalten, aber die Agenten und Chats, die auf den gelöschten Kanal verweisen, müssen vor weiterer Ausführung einen geeigneten Ersatzkanal auswählen.

Die Einstellungen des Kanals werden auf der Serverseite festgelegt – sie sind keine vordefinierten Einstellungen, die nur im Browser angezeigt werden. Die Zugangsdaten werden nicht über die üblichen Antworten des Kanalkatalogs zurückgegeben. Der State-Directory sowie die Backups sollten als Daten mit Zugangsdaten geschützt werden.

## Verbindungsprüfliste

1. Stellen Sie sicher, dass der Controller den API-Host erreichen kann und dass die TLS-Verbindung gültig ist.
2. Stellen Sie sicher, dass die Basispfad, das Protokoll, die Zugangsdaten sowie die genaue Modell-ID korrekt sind.
3. Entdecken Sie die neuen Möglichkeiten oder wählen Sie ein bekanntes Modell manuell aus.
4. Senden Sie zunächst einen kurzen, einfachen Text an den Bot. Anschließend können Sie eine kleine Anwendung ausführen.
5. Prüfen Sie die Fehlermeldungen bezüglich des Upstream-HTTP-Zustands, der Zeitverzögerungen oder der nicht unterstützten Optionen. Versuchen Sie nicht wiederholt, mit ungültigen Kreditkarten zu versuchen.

Weitere Informationen zur Handhabung von Rate Limits, Unterbrechungen beim Streaming sowie Autorisierungsfehlern finden Sie in [Administration und Fehlerbehebung](administration.md).
