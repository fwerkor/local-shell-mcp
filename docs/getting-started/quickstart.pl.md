<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# Szybki start

Ten przewodnik uruchamia kontroler LSM i otwiera interfejs przeglądarki. [unified web workspace](web-workspace.md) to zalecane codzienne doświadczenie; jest to oddzielnie wdrażany, opcjonalny stos czatów. ChatGPT, Gemini i inni zewnętrzni klienci MCP mogą łączyć się z tym samym kontrolerem. Zobacz [runtime choices and deployment model](../guides/deployment.md).

Zalecane jest **wdrożenie bezpośrednio ze źródeł** w odizolowanym środowisku. Docker Compose to alternatywa.

## Wymagania

- Git i Python 3.11+ z `venv` i `pip`.
- Publiczny HTTPS tylko dla użytkowników zdalnych lub zewnętrznych klientów MCP.
- Oddzielny katalog roboczy z ograniczonym dostępem.
- Silny PIN administratora OAuth i losowy sekret JWT.

!!! warning
    Połączony model może operować skonfigurowanym workspace. Uruchamiaj usługę w jednorazowym container lub VM i unikaj mountowania zasobów sterujących hostem.

## 1. Clone i konfiguracja

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

Edytuj `.env`, zastępując przykładowy PIN i sekret JWT (użyj `openssl rand -hex 32`). Uruchomienie ze źródeł nie wczytuje `.env` automatycznie.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Uruchomienie serwera

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Sprawdź stan w drugim terminalu:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Prawidłowa odpowiedź to HTTP `200`. Do stałego uruchomienia użyj menedżera usług.

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

Zaktualizuj źródła, ponownie zainstaluj pakiet editable i uruchom Controller ponownie:

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

Dla Docker Compose zaktualizuj kontenery:

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
