<!-- i18n-source-sha256: 1d80cfbe14747fb0691e91065f582d1e47eb36921d8b27da1648dcd26114a2e5 -->
# Runtime Python, pipx i source

Do zwykłego wdrożenia zalecamy [jeden plik wykonywalny](binary.md). Python i źródła służą programowaniu i dostosowaniu.

Ta strona obejmuje trzy powiązane przypadki:

- `pipx install local-shell-mcp`: instalacja executable na poziomie użytkownika.
- `pip install local-shell-mcp`: instalacja w istniejącym virtual environment.
- Editable source checkout: rozwijanie lub debugowanie samego projektu.

## Instalacja pipx

`pipx` jest najczystszą instalacją opartą na Python dla zwykłych użytkowników, ponieważ daje command własny virtual environment, jednocześnie udostępniając executable w `PATH`.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Uruchom lokalny HTTP MCP server:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Sprawdź stan:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Instalacja w virtual environment

Użyj, jeśli już samodzielnie zarządzasz środowiskami Python:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

Process używa narzędzi zainstalowanych na host. Pakiet Python nie instaluje za Ciebie compilerów, Git, browser system dependencies ani project dependencies.

## Editable source checkout

Źródła są przeznaczone do rozwoju; zwykle wybieraj [binarne wydanie](binary.md). OAuth/HTTPS: [szybki start](../getting-started/quickstart.md).

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Replace the example OAuth secrets in .env before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Uruchom kontrole:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Konfiguracja przeglądarki

Playwright jest opcjonalny; zainstaluj bibliotekę i przeglądarkę w razie potrzeby.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

Instalacja przeglądarki jest opcjonalna; bazowy obraz Docker nie zawiera Playwright ani przeglądarek.

## Publiczne użycie HTTP MCP

Dla ChatGPT lub innego public HTTP MCP client skonfiguruj te same ustawienia public-origin i OAuth co w innych runtime HTTP, a następnie expose local port przez reverse proxy lub tunnel.

Publiczny MCP endpoint:

```text
https://your-public-host.example.com/mcp
```

## Tryby deweloperskie

| Mode | Command | Zastosowanie |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | Pełne MCP client przez HTTP, w tym ChatGPT za HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Endpointy diagnostyczne lub zgodności, nie główna ścieżka ChatGPT |
| stdio | `local-shell-mcp --mode stdio` | Lokalne MCP client uruchamiające process |

`mode=both` jest zarezerwowany i obecnie nie powinien być używany jako mode pojedynczego process.

## Bezpieczeństwo host runtime

Instalacje Python działają jako host user, chyba że umieścisz je w VM/container. Ogranicz workspace, pozostaw full-container mode wyłączony i nie kieruj workspace na home directory.

Używaj Docker Compose dla niezaufanych repository, zadań intensywnie używających package manager lub workflow, w których resetability jest ważniejsze niż integracja z host.
