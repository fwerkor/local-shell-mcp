<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# Desktop-GUI-Automatisierung

`local-shell-mcp` kann native Desktop-Anwendungen unter Linux, Windows und macOS beobachten und steuern. Die öffentliche Fläche bleibt bewusst klein:

| Werkzeug | Zweck |
|---|---|
| `gui_list` | Listen Sie sichtbare Anwendungsfenster auf und melden Sie das aktive native Backend/die aktiven nativen Funktionen. |
| `gui_state` | Beobachten Sie ein Fenster. Gibt einen kurzlebigen `state_id`, Barrierefreiheitselemente, Fenstergeometrie und optional einen nativen MCP-Screenshot zurück. |
| `gui_action` | Führen Sie semantische oder koordinierende Aktionen für genau diese Beobachtung aus. |

Alle drei Tools akzeptieren optionales `machine`, sodass derselbe Workflow auf einen verbundenen Desktop-Mitarbeiter ausgerichtet sein kann.

## Beobachten, dann handeln

Beginnen Sie mit `gui_list`, wählen Sie einen `window_id` aus und rufen Sie dann `gui_state` auf. Bevorzugen Sie die zurückgegebene Zugänglichkeit `element_id`, wenn eine das Zielsteuerelement darstellt:

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Verwenden Sie fensterrelative `x`/`y`-Koordinaten nur, wenn die Benutzeroberfläche über kein nützliches Barrierefreiheitselement wie eine Leinwand oder ein benutzerdefiniertes Steuerelement verfügt. Zurückgegebene Elementgrenzen und Screenshots verwenden denselben fensterrelativen logischen Pixelraum, einschließlich HiDPI/Retina-Desktops. Rohkoordinaten außerhalb des ausgewählten Fensters werden abgelehnt.

Ein `state_id` läuft nach 30 Sekunden ab und ist für den einmaligen Gebrauch bestimmt. Koordinatenaktionen stellen außerdem sicher, dass sich das Zielfenster seit der Beobachtung nicht bewegt oder seine Größe geändert hat. Wenn eine der Prüfungen fehlschlägt, rufen Sie `gui_state` erneut auf, anstatt veraltete Koordinaten wiederzuverwenden.

Unterstützte Aktionen sind `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus` und `wait`.

## Menschliche Kontrolle in Native WebUI

Die native WebUI verfügt über eine **Desktop**-Seite für die direkte menschliche Steuerung derselben nativen GUI-Backends. Wählen Sie eine Maschine und ein Fenster aus und interagieren Sie dann mit dem Live-Fensterbild durch Klicken, Doppelklick, Rechtsklick, Ziehen, Rad, Tastaturkürzel oder das Textfeld für die IME/CJK-Eingabe.

Dieser Pfad ist absichtlich von der Semantik des Modells `state_id` getrennt. Jeder angezeigte Rahmen trägt die beobachtete Fenstergeometrie; Jede menschliche Eingabeanforderung überprüft, ob das Fenster immer noch genau diese Geometrie aufweist, bevor Eingaben eingefügt werden. Wenn das Fenster verschoben, in der Größe geändert oder verschwunden ist, wird die Aktion abgelehnt und die WebUI aktualisiert die Beobachtung. Rohkoordinaten bleiben an das ausgewählte Fenster gebunden.

Tastatur- und Textaktionen fokussieren vor der Injektion explizit das ausgewählte native Fenster. Die WebUI verwendet eine einfache Screenshot-Abfrage anstelle von VNC/WebRTC-Videostreaming, und der Nur-Remote-RPC `gui_human_action` ist ein interner Controller-zu-Worker-Vorgang und kein MCP-Tool, das Modellen zur Verfügung gestellt wird.

## Native Backends

| Plattform | Barrierefreiheit / semantische Kontrolle | Erfassung und Roheingabe |
|---|---|---|
| Windows | Microsoft-UI-Automatisierung | UIA-/Fenstererfassung plus native Windows-Maus- und Tastatureingabe |
| macOS | Barrierefreiheit (`AXUIElement`) | `screencapture` für das ausgewählte Fenster plus Quartz `CGEvent`-Eingabe |
| Linux | AT-SPI | X11 native Eingabe/Erfassung; Wayland verwendet native Desktop-Erfassung und XDG Desktop Portal RemoteDesktop/ScreenCast für die Roheingabe |

Semantische Aktionen werden nach Möglichkeit zuerst versucht. Eine Schaltfläche mit einer nativen Aufruf-/Drückaktion kann daher aktiviert werden, ohne eine Pixelkoordinate zu erraten. Visuelle Koordinaten bleiben der Ausweichpunkt für unzugängliche oder individuell gezeichnete Inhalte.

## Plattform-Setup

### Windows

Führen Sie LSM in derselben interaktiven Desktop-Sitzung aus wie die Anwendungen, die es steuern soll. Die Basisinstallation von `local-shell-mcp` bleibt Headless-sicher und erfordert keinen Windows-UI-Automatisierungsadapter; Installieren Sie das optionale Extra `local-shell-mcp[gui]`, wenn eine lokale Windows-GUI-Steuerung erforderlich ist.

### macOS

Gewähren Sie dem LSM-Hostprozess:

- **Barrierefreiheit**-Berechtigung für semantische Kontrolle und Eingabe.
- **Bildschirmaufzeichnung**-Berechtigung für Screenshots.

Das Basispaket erfordert kein PyObjC. Installieren Sie das optionale Extra `local-shell-mcp[gui]`, wenn eine lokale macOS-GUI-Steuerung erforderlich ist; Maschinen, die niemals GUI-Tools verwenden, benötigen diese Frameworks nicht.

### Linux

Die Desktop-Sitzung muss AT-SPI verfügbar machen. Debian/Ubuntu-Systeme stellen normalerweise die erforderlichen Systembindungen bereit mit:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

Das Basispaket erfordert keine Python X11- oder D-Bus-Adapter. Das optionale Extra `local-shell-mcp[gui]` installiert sie für die lokale GUI-Nutzung. Remote-Worker erkennen die aktive Linux-Sitzung vor einem GUI-Abhängigkeits-Bootstrap: X11 benötigt nur den X11-Adapter, Wayland benötigt nur den D-Bus-Adapter und Headless-Worker installieren keinen von beiden. Auf Wayland verwendet der Raw-Zeiger-/Tastatur-Fallback die XDG Desktop Portal RemoteDesktop-API, sodass auf dem Desktop möglicherweise eine einmalige Berechtigungs-/Sitzungsauswahl angezeigt wird. KDE- und GNOME-Portalimplementierungen werden unterstützt. Fenster-Screenshots nutzen den verfügbaren nativen Desktop-Erfassungspfad und greifen bei Bedarf auf das Screenshot-Portal zurück.

LSM-Worker starten üblicherweise außerhalb der grafischen Anmeldeumgebung. Das Linux-Backend stellt `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE` und zugehörige Variablen aus der Systemumgebung des Benutzers wieder her, wenn sie nicht direkt geerbt werden.

## Remote-Desktops

GUI-Tools werden auf dem ausgewählten Computer ausgeführt, nicht auf dem Controller. Der Remote-Worker muss zu dem Benutzer/der Sitzung gehören, der/die Eigentümer des Zieldesktops ist. GUI-Adapter sind träge und auf GUI-Aufrufe beschränkt: Beim normalen Worker-Start und bei der Verwendung von Shell/Dateien/Browser werden sie weder installiert noch importiert. Unter Linux gibt ein Headless-Worker die GUI nicht verfügbar zurück, bevor ein GUI-Pip-Bootstrap durchgeführt wird. Ein grafischer Mitarbeiter prüft oder installiert nur den Adapter, der für seine aktive X11- oder Wayland-Sitzung erforderlich ist.

Von einem Remote-`gui_state` zurückgegebene Screenshots werden über den Dateiübertragungspfad von LSM übertragen und dem Modell als nativer MCP-Bildinhalt zur Verfügung gestellt. Sie sind nicht in die JSON-Antwort des Workers eingebettet.
