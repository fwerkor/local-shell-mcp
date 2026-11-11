<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# Ujednolicony internetowy obszar roboczy

**Ujednolicony internetowy obszar roboczy LSM** to zalecany sposób codziennego korzystania z local-Shell-mcp. Łączy czat AI, historię projektu i płaszczyznę kontroli LSM w jednym responsywnym interfejsie, opartym na zmodyfikowanym, dostarczanym przez dostawcę interfejsie LibreChat. Nadal możesz podłączać zewnętrznych klientów MCP, takich jak [ChatGPT](chatgpt-connector.md) lub [Gemini](gemini-spark.md).

Obszar roboczy jest **samodzielny i można go zainstalować opcjonalnie**: jest oddzielną usługą internetową, a nie częścią minimalnego obrazu kontrolera, samodzielnego pliku wykonywalnego lub pakietu zdalnego pracownika. Wdrożenia oparte wyłącznie na kontrolerze zachowują oryginalny interfejs przeglądarki i OpenTUI.

## Co znajduje się w obszarze roboczym?

| Obszar | Co możesz zrobić |
|---|---|
| Czat i projekty | Wybierz skonfigurowany model, twórz rozmowy, organizuj projekty, odnajduj wcześniejsze czaty i archiwizuj rozmowy. Historia pozostaje na serwerze. |
| Przegląd kontrolera | Wyświetl stan, ostatnią aktywność i podłączone komputery. |
| Pliki | Przeglądaj i zarządzaj plikami lokalnymi lub zdalnymi. |
| Terminale | Pracuj ze stałymi terminalami na kontrolerze lub pracownikach. |
| Pulpit | Sprawdzaj i kontroluj zdalne sesje GUI. |
| Sesje | Sprawdź trwałe zadania LSM i ich cykl życia. |
| Piloty | Łącz i zarządzaj pracownikami wychodzącymi. |
| Audyt | Sprawdź działanie narzędzia pochodzącego z modelu. |
| Zagnieżdżone MCP | Zarejestruj, edytuj, włączaj, wyłączaj, odświeżaj i usuwaj zewnętrzne serwery MCP za LSM. |

Trasy kontrolera to `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` i `/control/audit`. Czat otwiera się pod adresem `/c/new`. Menedżer LSM MCP kontroluje **zagnieżdżony rejestr MCP LSM**; nie tworzy drugiego rejestru w LibreChat.

## Wdróż opcjonalny stos czatu

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## Zaloguj się i korzystaj z czatu

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Przesyłane czaty (do 32 MiB) są przechowywane w obszarze roboczym Kontrolera, a ich ścieżki bezwzględne są dostarczane do modelu. Przesyłanie przez przeglądarkę nie przyznaje dodatkowych uprawnień do plików. Wywołania narzędzi skierowanych do modelu przechodzą przez autoryzację LSM, audyt i router pracownika zdalnego.

## Zewnętrzny MCP, bezpieczeństwo i dane

Użyj paska bocznego MCP obszaru roboczego, aby zarządzać zagnieżdżonymi zewnętrznymi serwerami MCP. Obsługuje to lokalne serwery stdio i serwery HTTP, w tym oddzielne prywatne zmienne środowiskowe i nagłówki żądań. Sekrety nie są zwracane do przeglądarki. Przełącznik czatu **zewnętrznego MCP** umożliwia wyszukiwanie, sprawdzanie i wywoływanie zagnieżdżonych narzędzi; nie przyznaje modelu `mcp_manage`, gdy natywne narzędzia LSM są wyłączone. Zarządzanie interfejsem użytkownika jest chronione zwykłą autoryzacją kontrolera.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Rozwiązywanie problemów

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Szczegóły implementacji i aktualizacje można znaleźć w plikach [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) i [human interface guide](../guides/human-interface.md).
