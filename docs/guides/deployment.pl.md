<!-- i18n-source-sha256: 594169d44520f8abd7cebee1bfa42c5ff0ca31f424115d438107ed01b77fa604 -->
# Wybór runtime i model deploymentu

`local-shell-mcp` ma dwie uzupełniające się decyzje:

1. **Runtime**: jak działa proces serwera i jaki workspace kontroluje.
2. **Interfejs**: użyj opcjonalnego [unified web workspace](../getting-started/web-workspace.md) lub podłącz zewnętrznego klienta MCP, takiego jak Gemini lub ChatGPT.

Zalecanym codziennym interfejsem jest własny hostowany internetowy obszar roboczy (czat, projekty i strony kontrolne LSM). Jest wdrażany niezależnie od kontrolera. Docker, rozszerzenie VS Code, pliki binarne wersji, instalacje Pythona i tryb stdio to sposoby na uruchomienie kontrolera; zewnętrzne aplikacje do czatowania pozostają opcjonalnymi klientami.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Utwórz lokalny, tylko HTTP, ujednolicony internetowy obszar roboczy
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Typową konfiguracją hostowaną samodzielnie jest:

```text
Przeglądarka -> https://chat.example.com (ujednolicony internetowy obszar roboczy)
        -> uwierzytelniony kontroler local-shell-mcp
        -> kontrolowany obszar roboczy i pracownicy wychodzący
Opcjonalny klient zewnętrzny -> https://mcp.example.com/mcp
```

Lokalny setup MCP client może być prostszy:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

## Macierz wyboru runtime

| Czas wykonania | Najlepsze dla | Granica izolacji | Źródło łańcucha narzędzi | Zewnętrzny dostęp do MCP | Strona |
|---|---|---|---|---|---|
| Tworzenie Dockera | Większość obciążeń agenta kodowania i powtarzalnych obszarów roboczych | Pojemnik | Obraz kontrolera Lean; zainstaluj osobno łańcuchy narzędzi specyficzne dla zadania | Dodaj serwer proxy lub tunel HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + wózek boczny z tunelem | Wdrożenie kontrolera publicznego za pomocą tunelu Cloudflare | Pojemnik | Obraz projektu | Wbudowany w profil Compose `tunnel` | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Start/stop server z editor workspace | Zwykle host process | Host tools plus configured executable | Dodaj zewnętrzny HTTPS tunnel/proxy dla ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Host lub VM bez Docker | Host or VM | Host tools plus configured executable | Dodaj HTTPS proxy lub tunnel | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Użycie Python-native, debugging, development | Host virtualenv or VM | Python package plus host tools | Dodaj HTTPS proxy lub tunnel | [Python install](../installation/python.md) |
| Stdio mode | Lokalne MCP clients bezpośrednio spawnujące procesy | Client process boundary | Host tools plus configured executable | Nieużywalny z ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Macierz połączeń client

| Interfejs | Wymaga publicznego protokołu HTTPS | Używa `/mcp` | Wymaga OAuth | Typowy czas działania |
|---|---:|---:|---:|---|
| Ujednolicony internetowy obszar roboczy LSM | Tak dla zdalnego dostępu; możliwe jest również lokalne proxy | Wewnętrznie | Logowanie do LSM | Kontroler plus oddzielny stos sieciowy |
| Gemini Spark / Aplikacje niestandardowe | Tak | Tak | Tak, do użytku publicznego | Dowolny kontroler HTTP |
| ChatGPT custom MCP connector | Tak | Tak | Tak dla użycia publicznego | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | Nie | Nie | Nie | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Zwykle nie na localhost; tak między sieciami | Tak | Zalecane poza localhost | Any HTTP runtime |
| VS Code extension helper flow | Tylko jeśli ChatGPT ma się łączyć | Tak przy kopiowaniu ChatGPT URL | Zalecane dla ChatGPT | VS Code-launched runtime |

Zobacz [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) i [network connectivity](../clients/connectivity.md).

## Co kontroluje każdy runtime

Każdy runtime uruchamia ten sam server code i udostępnia te same family MCP tools, jeśli są włączone:

- Shell i persistent shell sessions.
- Filesystem, search i patch tools.
- Git operations.
- Browser automation przez Playwright.
- Audit log i task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle i machine-routed tools.

Różnica nie dotyczy abstract API, lecz **operating environment** za nim.

| Pytanie | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Gdzie działają komendy? | W container | Zwykle w host workspace | W host lub VM process environment |
| Default workspace? | Mounted `/workspace` | Bieżący folder VS Code lub configured path | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Czy kompilatory i przeglądarki są preinstalowane? | NIE; zainstaluj to, czego potrzebuje zadanie | Tylko jeśli jest zainstalowany na hoście | Tylko jeśli jest zainstalowany na hoście |
| Czy reset jest łatwy? | Odtwórz container i workspace volume | Zależy od workspace | Zależy od host/VM |
| Dobre do arbitrary package install? | Tak, jeśli disposable | Ryzykowniejsze na host | Ryzykowniejsze poza VM |

## Zalecany wybór

Najpierw użyj **Docker Compose**, chyba że masz powód, aby tego nie robić. Zapewnia wyraźną granicę bezpieczeństwa bez konieczności posiadania dużego, preinstalowanego zestawu narzędzi programistycznych.

Użyj **rozszerzenia VS Code**, gdy przepływ pracy rozpoczyna się w edytorze i chcesz mieć lokalny program uruchamiający. To wciąż czas wykonania. Zdalni klienci sieciowi potrzebują osiągalnego serwera proxy lub tunelu HTTPS.

Użyj **standalone binary**, jeśli Docker jest niedostępny, ale VM, container host lub dedicated user account już tworzy boundary.

Użyj **`pipx` lub source install** do development/debugging `local-shell-mcp` albo gdy Python-based environment jest łatwiejsze w utrzymaniu.

Użyj **stdio mode** tylko dla lokalnych MCP clients zdolnych spawnować server process. Nie jest to public deployment i ChatGPT web/app nie użyje go bezpośrednio.

## Reguła public endpoint

W przypadku zewnętrznych klientów HTTP MCP, takich jak Gemini i ChatGPT, punktem końcowym MCP jest:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` zawiera tylko origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Nie dodawaj `/mcp` do `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Strony runtime

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Strony client

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
