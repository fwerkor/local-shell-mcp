<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# Interfejs użytkownika

`local-shell-mcp` udostępnia dwa zgodne interfejsy człowieka nad tym samym service API, workspace, rejestrem persistent terminals, rejestrem remote workers i logiem audytu MCP:

- **Web UI** to natywny panel przeglądarkowy zoptymalizowany pod szybki podgląd operacyjny.
- **OpenTUI** to pełna aplikacja terminalowa, dostępna zarówno w przeglądarce, jak i jako natywne polecenie terminala.

Żaden tryb nie tworzy osobnego control plane. Zmiana interfejsu nie zmienia podłączonych maszyn, Sessions, jobs, uprawnień ani danych audytowych.

## Uruchamianie usługi

Uruchom `local-shell-mcp` normalnie:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

Gdy ChatGPT renderuje MCP Apps, `workspace_open(session_id=...)` otwiera pływający widok współpracy dla **jawnie wybranej Logical Session**. Session przechowuje trwały stan zadania — objective, progress, Plan i Activity — a Live Workspace jedynie prezentuje ten stan, aktywność na żywo i kontrolki dla człowieka. Nigdy nie wywnioskuje tożsamości zadania z transportu MCP.

Typowy jawny handoff wygląda tak:

```text
session_manage(action="start", objective=...)
        -> session_id
... wywołania narzędzi z logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
nowa rozmowa ChatGPT
użytkownik przekazuje wcześniejszy session_id
session_manage(action="resume", session_id=...)
        -> istniejący progress, Plan i ostatnia Activity
workspace_open(session_id=...)
        -> widok tej samej Session
```

`session_id` jest jedyną trwałą tożsamością zadania. Agent nie może listować, wnioskować ani automatycznie wybierać Session z innej rozmowy. Aby kontynuować pracę w nowej rozmowie, użytkownik jawnie przekazuje istniejący `session_id`. Agent powinien podawać aktywny `session_id` po start/resume, przy istotnych checkpointach postępu oraz przed zakończeniem turn, aby umożliwić ręczny handoff. Sessions nie są związane z machine ani working directory; zwykłe parametry narzędzi nadal wybierają lokalne/zdalne targets i paths.

Opcjonalny Plan `plan_manage` włącza Goal mode dla Session. Jeśli Plan jest active i przez 15 minut nie ma agent activity, powiązany Live Workspace może poprosić ChatGPT o kontynuowanie. Continuation wznawia ten sam jawny `session_id` i jest ograniczona do 10 prób, zaakceptowanych lub odrzuconych. Plans blocked, completed i cancelled nie są automatycznie kontynuowane; active Plan, którego wszystkie steps są completed lub skipped, pozostaje dostępny dla końcowej continuation, aby wznowiony agent mógł zakończyć Plan. Kontrolki pause/resume/cancel obsługiwane przez człowieka aktualizują Plan należący do Session, a nie ulotny stan Live Workspace.

## Interfejs przeglądarkowy

Otwórz:

```text
http://127.0.0.1:8765/ui
```

W publicznym deployment użyj skonfigurowanego HTTPS origin:

```text
https://your-public-host.example.com/ui
```

Interfejs przeglądarkowy korzysta z tego samego serwera OAuth i tych samych scopes co MCP. Szkielet strony i statyczne zasoby są publiczne, aby ekran logowania mógł się załadować, natomiast `/api/ui/*` i WebSocket terminala OpenTUI pozostają chronione. Tokeny dostępu są przechowywane wyłącznie w session storage przeglądarki.

### Wybór interfejsu

Ekran OAuth oferuje dwa wejścia:

- **Open Web UI** autoryzuje i otwiera natywny panel.
- **Continue to OpenTUI** autoryzuje i otwiera interfejs terminalowy, zachowując dotychczasowe zachowanie przeglądarki.

Po autoryzacji selektor na pasku bocznym przełącza Web UI i OpenTUI bez ponownego logowania. Bieżąca natywna strona jest zapamiętywana przy tymczasowym przejściu do OpenTUI.

Trasy można zapisywać w zakładkach:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` i `#/dashboard` są aliasami Overview. `#/tui` i `#/opentui` są aliasami Console.

## Natywny Web UI

Natywny Web UI odpytuje istniejące API interfejsu użytkownika co pięć sekund i renderuje natywne kontrolki przeglądarki zamiast komórek terminala. PTY nie jest uruchamiany przed wybraniem OpenTUI.

### Overview

Overview najpierw pokazuje najważniejsze informacje operacyjne:

- Stan controller i bieżącą wersję LSM.
- Liczbę maszyn online i offline.
- Aktywne tracked jobs i trwałe sesje terminalowe.
- CPU, pamięć, dysk workspace, load, przepustowość sieci i uptime.
- Alerty generowane ze stanu workers, progów zasobów, nieudanych jobs i nieudanych wywołań MCP.
- Ostatnią aktywność MCP rozpoczętą przez model.

### Machines

Machines pokazuje lokalny controller i połączonych zdalnych workers wraz ze stanem, platformą, wersją, katalogiem roboczym, możliwościami i informacją last-seen.

### Workloads

Workloads łączy aktywne tracked jobs i samodzielne trwałe sesje shell. Web UI pozostaje tylko do odczytu dla tych rekordów; do interaktywnego zarządzania sesjami użyj OpenTUI.

### Activity

Activity łączy bieżące alerty z ostatnią aktywnością audytu MCP. Polecenia i operacje na plikach wprowadzone przez człowieka nie są zapisywane w dzienniku audytu MCP.

## OpenTUI w przeglądarce

Wybranie **OpenTUI** uruchamia na żądanie tę samą aplikację OpenTUI, której używa natywny launcher terminala. Console przeglądarki zachowuje:

- Uwierzytelniony binarny transport PTY przez WebSocket.
- Automatyczną zmianę rozmiaru terminala i backoff ponownego łączenia.
- Obsługę myszy dla kontrolek OpenTUI.
- Tryb pełnoekranowy i bezpieczne dla przeglądarki skróty klawiszowe.
- Mobilne klawisze skrótów i jawne sterowanie klawiaturą ekranową.
- Obsługę SIXEL i inline image przez xterm.js.

Przeglądarka nie tworzy PTY OpenTUI, dopóki użytkownik pozostaje w natywnym trybie Web UI.

## Natywny OpenTUI

Samodzielne pliki wykonywalne release zawierają platformowy runtime OpenTUI. Zachowaj tylko główny plik wykonywalny, uruchom usługę, a następnie wykonaj:

```bash
local-shell-mcp tui
```

Natywny TUI nie wymaga logowania od operatora. W udokumentowanej konfiguracji Docker Compose launcher ponownie używa dedykowanej credential CLI przechowywanej wyłącznie na hoście do Human UI API przez loopback; inne układy split-runtime mogą użyć `--token-file`. Instancje OpenTUI uruchamiane z przeglądarki używają credential utrzymywanej tylko w procesie controllera, tworzonej leniwie i nigdy nie zapisywanej w state directory ani state backend. Reverse proxy nie otrzymuje żadnego z tych lokalnych bypassów tylko dlatego, że łączy się przez loopback.

Source checkout może także uruchamiać TUI po zainstalowaniu zależności Bun:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

Używaj `--api-base` tylko wtedy, gdy lokalna usługa działa na niestandardowym porcie:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## Ekrany OpenTUI

### Dashboard

Dashboard to operacyjny przegląd OpenTUI. Szerokie terminale pokazują osobne regiony node, workload, alert, activity, informacji systemowych i trendów; węższe terminale składają je do kompaktowych podsumowań bez przewijania poziomego.

### Files

Files to natywny dla LSM trójpanelowy menedżer plików dla maszyn lokalnych i zdalnych. Oferuje tworzenie, edycję, zmianę nazw, kopiowanie, przenoszenie, wklejanie, usuwanie, przełączanie plików ukrytych, odświeżanie, podgląd tekstu, podgląd binarny i ograniczone miniatury obrazów.

### Terminals

Terminals zarządza trwałymi sesjami shell na maszynach lokalnych i zdalnych. Obsługuje pełne polecenia, raw input interaktywny, zmianę sesji, tworzenie i kończenie sesji, ostatni output oraz zwijany rail audytu MCP.

### Audit

Audit odczytuje ograniczony dziennik audytu JSONL i obsługuje filtry node, operation, event, session, search, time-range i sort oraz podgląd szczegółów rekordów.

### Remotes

Remotes pokazuje zdalnych workers online i offline, możliwości, katalogi robocze i metadane systemu. Może utworzyć jednorazowe join invite, zmienić nazwę node lub unieważnić jego trwałą identity.

## Nawigacja OpenTUI

Górny pasek kategorii i kontekstowe akcje footer można klikać myszą zarówno w natywnych terminalach, jak i w console przeglądarki.

| Klawisze | Akcja |
|---|---|
| `Alt+1` … `Alt+5` | Otwiera Dashboard, Files, Terminals, Remotes lub Audit. |
| `F2` … `F6` | Alternatywne skróty kategorii. |
| `F1` | Otwórz przewodnik po klawiaturze. |
| `F9` | Odśwież listę maszyn. |
| `Alt+Q` | Zakończ natywny proces OpenTUI bez wywoływania skrótu Ctrl zarezerwowanego przez przeglądarkę. |

Terminals używa `Alt+N` dla nowej sesji, `Alt+W` do zakończenia wybranej sesji, `Alt+A` do przełączania rail audytu, `Alt+R` do odświeżania i `Alt+Left/Right` do przełączania sesji. Console przeglądarki przechwytuje te kombinacje przed nawigacją lub obsługą menu przez przeglądarkę.

## Konfiguracja

| Klucz YAML | Zmienna środowiskowa | Domyślna | Cel |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Montuje lub wyłącza interfejsy użytkownika. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | Ścieżka montowania interfejsu przeglądarkowego w usłudze MCP. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Nadpisuje wyszukiwanie natywnego pliku OpenTUI. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | Ustawienie tapety zachowane dla deploymentów console OpenTUI w przeglądarce. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Zamyka nieaktywny PTY OpenTUI w przeglądarce po tej liczbie sekund; `0` wyłącza timeout. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Maksymalna liczba jednoczesnych sesji PTY OpenTUI w przeglądarce. |

## Uwagi o pakowaniu

- Obrazy Docker zawierają zasoby Web UI i natywny runtime OpenTUI.
- Samodzielne pliki wykonywalne zawierają zasoby Web UI i skompresowany platformowy runtime OpenTUI.
- Python wheels zawierają zasoby przeglądarkowe; natywny OpenTUI wymaga pliku wykonywalnego release albo source checkout z zainstalowanymi zależnościami Bun.
- Oba interfejsy są obsługiwane przez ten sam proces i port co MCP; dodatkowa usługa web nie jest potrzebna.
