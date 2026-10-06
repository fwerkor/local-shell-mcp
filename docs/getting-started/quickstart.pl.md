<!-- i18n-source-sha256: a3fdf9088031e6903b15497a3df881a8e6ed2f6f2b34dd4d0b68b0414a2ca81e -->
# Szybki start

Ten przewodnik używa Docker Compose jako pierwszego runtime, a ChatGPT jako pierwszego client. To niezależne wybory: Docker, VS Code extension, binary, Python i stdio są opcjami runtime; ChatGPT i ogólne klienty MCP są opcjami client. Pełną mapę opisuje [wybór runtime i model deploymentu](../guides/deployment.md).

## Wymagania

- Docker Engine z Compose v2.
- Publiczny endpoint HTTPS, jeśli ChatGPT ma łączyć się z Web.
- Dedykowany katalog workspace.
- Długi losowy OAuth admin PIN i JWT secret.

!!! warning
    Połączony model może operować skonfigurowanym workspace. Uruchamiaj usługę w jednorazowym container lub VM i unikaj mountowania zasobów sterujących hostem.

## 1. Clone i konfiguracja

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

Edytuj `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. Uruchomienie serwera

```bash
mkdir -p workspaces/default
docker compose up -d
```

Sprawdź stan:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Poprawna odpowiedź zwraca HTTP `200`.

## 3. Udostępnienie HTTPS

Dla sidecar Cloudflare Tunnel:

```bash
docker compose --profile tunnel up -d
```

W Cloudflare Zero Trust skieruj public hostname na:

```text
http://local-shell-mcp:8765
```

Dla Caddy, Nginx, Traefik, Nginx Proxy Manager lub innego reverse proxy przekieruj HTTPS traffic do `127.0.0.1:8765` albo adresu sieciowego container.

## 4. Połączenie ChatGPT

Użyj MCP endpoint:

```text
https://your-public-host.example.com/mcp
```

Postępuj zgodnie z [przewodnikiem connectora ChatGPT](chatgpt-connector.md), aby ukończyć OAuth i zatwierdzenie tools.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Jeśli używasz profilu tunnel:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
| Dodanie ChatGPT jako client | [ChatGPT connector](chatgpt-connector.md) |
| Wybór tools i lepsze prompty | [Wzorce użycia](../guides/usage-patterns.md) |
| Podłączenie maszyny HPC, NPU/GPU lub NAT | [Zdalni workers](../guides/remote-workers.md) |
| Zrozumienie wszystkich MCP tools | [Referencja tools](../reference/tools.md) |
