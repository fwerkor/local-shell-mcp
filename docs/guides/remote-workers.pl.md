<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Zdalne workers

Remote workers pozwalają `local-shell-mcp` kontrolować maszyny, które mogą wykonywać wychodzące żądania HTTP(S), ale nie mogą przyjmować przychodzących połączeń SSH.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Podstawowy workflow

1. Utwórz zaproszenie przez `remote_manage(action="invite", ...)`.
2. Uruchom wygenerowane polecenie na zdalnej maszynie.
3. Potwierdź rejestrację przez `remote_manage(action="list")`.
4. Wywołuj zwykłe narzędzia z `machine="<worker-name>"`, np. `environment_get`, `run_shell`, `file_read` lub `browser_run_script`.
5. Użyj `remote_transfer`, aby rozpocząć śledzony transfer pliku/katalogu controller-to-worker, worker-to-controller lub worker-to-worker. Śledź go przez `job_list` lub `job_tail`; zatrzymaj lub ponów przez `job_stop` albo `job_retry`.
6. Zmieniaj nazwę lub unieważniaj workers przez `remote_manage(action="rename", ...)` lub `remote_manage(action="revoke", ...)`.

Domyślnie zaproszenie pozwala zarejestrować jednego workera (`max_uses=1`). Zwiększ `max_uses`, aby zarejestrować wielu workerów za pomocą tego samego zaproszenia. Dla zaproszeń wielokrotnego użytku pozostaw `name` puste. Opcjonalny parametr `ttl_s` domyślnie wynosi dwie godziny (7200 sekund), a maksymalnie siedem dni (604800 sekund).

Tylko administracja workers używa nazw `remote_*`. Operacje execution, shell, job, filesystem, patch i browser współdzielą ten sam schema lokalnie i zdalnie. Podanie machine wymaga dodatkowo OAuth scope `remote:use`.

## Trwałe workers

Wynik zaproszenia zawiera polecenia zależne od platformy:

- `persistent_command` instaluje i uruchamia user service na Linux/macOS.
- `powershell_persistent_command` instaluje i uruchamia Windows user task z PowerShell.

W Windows `local-shell-mcp worker install-service` rejestruje zadanie `local-shell-mcp-worker` dla bieżącego użytkownika. Uruchamia się od razu, ponownie po reboot po zalogowaniu tego użytkownika, zezwala na działanie na baterii, ignoruje zduplikowane uruchomienia i ponawia nieudane wykonania. Nie wymaga praw administratora i nie działa przed logowaniem użytkownika.

Na wszystkich platformach używaj tych samych lifecycle commands:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

Worker log jest zapisywany w worker state directory jako `worker.log`.

## Możliwości

Workers obsługują shell/persistent shell sessions, tracked jobs, operacje filesystem, transfer internals, wykonywanie Python, patches oraz Playwright, jeśli zależności są zainstalowane. Git używa standardowych poleceń przez `run_shell(machine=...)`.

## Bezpieczeństwo i wersjonowanie

Dołączony worker daje MCP client kontrolę nad skonfigurowanym środowiskiem. Używaj krótkich invite TTL, dedykowanych work directories lub kont, przeglądaj audit logs i unieważniaj workers po zadaniu. Wygenerowane zaproszenie instaluje worker code zgodny z wersją control server.

## Rozwiązywanie problemów

Jeśli worker się nie pojawia, sprawdź outbound HTTPS access, osiągalność public base URL, invite expiry, system time i logi control server.
