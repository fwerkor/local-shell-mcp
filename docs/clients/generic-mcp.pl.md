# Ogólne klienty MCP

Ta strona opisuje scenariusz „Ogólne klienty MCP” i zachowuje wspólną strukturę Runtime/Client dokumentacji.

## Przegląd

Runtime określa, jak działa proces serwera i którym workspace steruje. Client określa, jak łączy się ChatGPT lub inny klient MCP. Docker, rozszerzenie VS Code, samodzielne pliki binarne, instalacje Python/pipx/ze źródeł i stdio to opcje Runtime; łącznik ChatGPT, ogólny klient HTTP MCP i klient MCP stdio to połączenia Client.

## Kiedy używać

- Użyj tej strony, gdy wybrana ścieżka Runtime lub Client odpowiada tytułowi.
- Zachowaj spójność katalogu głównego workspace, publicznego base URL, MCP endpoint, trybu uwierzytelniania i dostępnych narzędzi hosta.
- Dla ChatGPT web/app wystaw HTTPS MCP endpoint kończący się na `/mcp`.
- Dla lokalnych klientów MCP użyj HTTP localhost albo `local-shell-mcp --mode stdio` zależnie od obsługi klienta.

## Kroki

1. Najpierw wybierz stronę instalacji Runtime.
2. Uruchom Runtime i sprawdź `/healthz`, gdy używany jest tryb HTTP.
3. Następnie wybierz stronę połączenia Client.
4. Zarejestruj MCP endpoint albo polecenie stdio w Client.
5. Wywołaj `environment_info`, aby sprawdzić rzeczywisty workspace i ustawienia.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Weryfikacja

- `environment_info` potwierdza ustawienia Runtime i workspace.
- `tree_view` potwierdza widoczne pliki.
- `git_status_tool` potwierdza kontekst repozytorium.
- `run_shell_tool` potwierdza środowisko poleceń.

## Uwagi

Preferuj małe, weryfikowalne kroki: inspekcja, edycja, diff, test, skanowanie i commit. Duże zadania również należy dzielić na audytowalne wywołania narzędzi.
