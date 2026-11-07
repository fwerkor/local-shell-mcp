<!-- i18n-source-sha256: cef0a90f9de3e2806e2a6bd8925217ea44ea6d6e6bce911eea09b1d4192a82d9 -->
# Wybór runtime i model deploymentu

`local-shell-mcp` ma dwie uzupełniające się decyzje:

1. **Runtime**: jak działa proces serwera i jaki workspace kontroluje.
2. **Interfejs**: użyj opcjonalnego [unified web workspace](../getting-started/web-workspace.md) lub podłącz zewnętrznego klienta MCP, takiego jak Gemini lub ChatGPT.

**Controller zalecamy uruchamiać z jednego pliku wykonywalnego**, bez Python, Dockera czy źródeł. Inne warianty są dostępne.

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

**Zalecane:** Do dostępu publicznego użyj serwera z publicznym adresem lub przekierowania przez serwer publiczny z odwrotnym proxy HTTPS. **Niezalecane:** Przesyłanie danych od klienta przez Cloudflare Tunnel może być bardzo wolne, co utrudnia wysyłanie i transfer plików. Używaj tylko wtedy, gdy serwer publiczny lub przekierowanie nie są dostępne. ([Public HTTPS exposure](../clients/connectivity.md))

## Macierz wyboru runtime

| Czas wykonania | Najlepsze dla | Granica izolacji | Źródło łańcucha narzędzi | Zewnętrzny dostęp do MCP | Strona |
|---|---|---|---|---|---|
| **Jeden plik (zalecane)** | Większość wspieranych systemów | Host or VM | Host tools plus configured executable | Dodaj HTTPS proxy lub tunnel | [Standalone binary](../installation/binary.md) |
| Tworzenie Dockera | Izolowane i jednorazowe kontenery | Pojemnik | Obraz kontrolera Lean; zainstaluj osobno łańcuchy narzędzi specyficzne dla zadania | Dodaj serwer proxy lub tunel HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + wózek boczny z tunelem | Niezalecane: Przekierowanie przez serwer publiczny; Cloudflare Tunnel tylko awaryjnie | Pojemnik | Obraz projektu | Przekierowanie przez serwer publiczny; Cloudflare Tunnel tylko awaryjnie | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Start/stop server z editor workspace | Zwykle host process | Host tools plus configured executable | Dodaj zewnętrzny HTTPS tunnel/proxy dla ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Źródła / pipx | Rozwój i dostosowanie | Host virtualenv or VM | Python package plus host tools | Dodaj HTTPS proxy lub tunnel | [Python install](../installation/python.md) |
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

**Wybierz pojedynczy plik**: pobierz wersję dla platformy i uruchom na koncie z ograniczeniami w osobnym workspace. [Poradnik binarny](../installation/binary.md).

Użyj **rozszerzenia VS Code**, gdy przepływ pracy rozpoczyna się w edytorze i chcesz mieć lokalny program uruchamiający. To wciąż czas wykonania. Zdalni klienci sieciowi potrzebują osiągalnego serwera proxy lub tunelu HTTPS.

**Instalacja ze źródeł** służy rozwojowi, debugowaniu i modyfikacjom w Python. [Poradnik Python](../installation/python.md).

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
