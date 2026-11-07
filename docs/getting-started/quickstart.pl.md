<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Szybki start

Ten przewodnik uruchamia kontroler LSM i otwiera interfejs przeglądarki. [unified web workspace](web-workspace.md) to zalecane codzienne doświadczenie; jest to oddzielnie wdrażany, opcjonalny stos czatów. ChatGPT, Gemini i inni zewnętrzni klienci MCP mogą łączyć się z tym samym kontrolerem. Zobacz [runtime choices and deployment model](../guides/deployment.md).

Zalecamy **pojedynczy plik wykonywalny Controllera** z [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest), bez Python, Dockera i źródeł. Przykład dla **Linux x86_64**; inne platformy: [instalacja binarna](../installation/binary.md).

## Wymagania

- Zgodny plik wykonywalny i `curl` (przykład Linux x86_64).
- Publiczny HTTPS tylko dla zdalnych użytkowników lub klientów MCP.
- Oddzielny i ograniczony workspace.
- Silny PIN OAuth i losowy sekret JWT.

!!! warning
    Połączony model może operować skonfigurowanym workspace. Uruchamiaj usługę w jednorazowym container lub VM i unikaj mountowania zasobów sterujących hostem.

## 1. Pobranie pliku i konfiguracja

Pobierz jeden plik wykonywalny i wygeneruj sekret JWT:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

Utwórz `.env` i zastąp przykładowe PIN oraz sekret JWT (użyj `openssl rand -hex 32`). Plik binarny **nie wczytuje automatycznie** `.env`.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Uruchomienie serwera

Uruchom pobrany plik bezpośrednio:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Sprawdź stan w drugim terminalu:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Poprawna odpowiedź to HTTP `200`. Do ciągłej pracy użyj menedżera usług i ograniczonego konta.

## 3. Udostępnienie HTTPS

Do zdalnego dostępu użyj publicznego serwera lub zwrotnego proxy HTTPS (Caddy, Nginx, Traefik), przekazując całą witrynę z wysyłaniem plików do:

```text
http://127.0.0.1:8765
```

Sprawdź HTTPS:

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel nie jest zalecany** do przesyłania plików: upload klienta bywa wolny. Preferuj publiczny serwer lub zwykły reverse proxy/przekierowanie portów z OAuth. Alternatywa: [Docker](../installation/docker.md).

## 4. Otwórz obszar roboczy przeglądarki

Otwórz login kontrolera:

```text
https://twój-publiczny-host.example.com/ui
```

W przypadku czatów, projektów i zintegrowanych stron kontrolnych postępuj zgodnie z [unified web workspace guide](web-workspace.md). Oryginalny, lekki interfejs WebUI jest dostępny, gdy czat nie jest zainstalowany.

## 5. Bezpieczne potwierdzenie dostępu do tools

Poproś model:

```text
Użyj local-shell-mcp. Najpierw wywołaj environment_get, potem wylistuj root workspace. Jeszcze nie modyfikuj plików.
```

Oczekiwane read-only tools:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Zacznij od ograniczonego coding task

Dobre pierwsze zadanie:

```text
Sprawdź to repository, podsumuj layout projektu, uruchom istniejący test suite, jeśli jest oczywisty, i nie zmieniaj plików.
```

Po potwierdzeniu łączności podaj bardziej szczegółowe instrukcje:

```text
Napraw failing test. Najpierw przeczytaj odpowiednie pliki, wykonaj najmniejszy patch, uruchom docelowy test, potem pokaż git diff. Nie rób commit przed moją zgodą.
```

## Aktualizacja

Zastąp plik wykonywalny i uruchom Controller ponownie:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

W Docker Compose aktualizuj kontener; źródła: [Python](../installation/python.md).

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## Następne strony

| Potrzeba | Strona |
|---|---|
| Zrozumienie wyborów runtime i client | [Wybór runtime i model deploymentu](../guides/deployment.md) |
| Uruchomienie z Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Uruchomienie z VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Uruchomienie z release binary | [Standalone binary runtime](../installation/binary.md) |
| Uruchomienie z Python lub source checkout | [Python runtimes](../installation/python.md) |
| Skorzystaj z ujednoliconego interfejsu czatu i kontroli | [Unified web workspace](web-workspace.md) |
| Dodaj Gemini Spark jako klienta | [Gemini Custom Apps](gemini-spark.md) |
| Dodanie ChatGPT jako client | [ChatGPT connector](chatgpt-connector.md) |
| Wybór tools i lepsze prompty | [Wzorce użycia](../guides/usage-patterns.md) |
| Podłączenie maszyny HPC, NPU/GPU lub NAT | [Zdalni workers](../guides/remote-workers.md) |
| Zrozumienie wszystkich MCP tools | [Referencja tools](../reference/tools.md) |
