<!-- i18n-source-sha256: ed47d5e0691f17af5cd4758981c31957e299202bf72433b34b4656346312091e -->
# Samodzielny binary runtime

Zalecamy **pojedynczy plik wykonywalny Controllera** z GitHub Releases, bez Python, Dockera i źródeł.

To wybór runtime. Dostęp ChatGPT konfiguruje się osobno przez HTTPS endpoint `/mcp`.

## Release artifacts

GitHub Releases buduje self-contained executables dla popularnych platform:

| Platform artifact | Archive |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

Każdy archive zawiera executable, README, license i krótki quickstart file.

Dostępny jest także **pojedynczy plik wykonywalny**. Zawiera tylko Controller i natywne WebUI; chat, bazy danych, Worker, narzędzia i przeglądarki są osobne.

## Instalacja

1. Pobierz plik wykonywalny lub archiwum dla platformy z [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest).
2. Jeśli wybrano archiwum, rozpakuj je.
3. Umieść executable w `PATH` lub zapisz jego absolute path.
4. Uruchom `local-shell-mcp --help`, aby potwierdzić start binary.

Przykład: bezpośrednie pobranie pliku dla Linux x86_64; na innych platformach wybierz odpowiedni plik:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
```

W Windows uruchamiaj `local-shell-mcp.exe` z PowerShell lub dodaj zawierający go directory do `PATH`.

## Minimal local run

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
~/lsm/local-shell-mcp --mode mcp
```

W innym terminalu:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Public HTTP MCP run

Dla ChatGPT lub public HTTP MCP client ustaw następujące kategorie configuration:

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | Directory kontrolowany przez tools |
| `LOCAL_SHELL_MCP_HOST` and `LOCAL_SHELL_MCP_PORT` | Local bind address i port |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | Public HTTPS origin bez `/mcp` |
| `LOCAL_SHELL_MCP_AUTH_MODE` | Dla public deployment użyj `oauth` |
| OAuth PIN and JWT secret settings | Wymagane do public OAuth authorization |

Expose local HTTP port przez reverse proxy lub tunnel. Public endpoint:

```text
https://your-public-host.example.com/mcp
```

## YAML config

YAML config może przechowywać niesekretne runtime defaults:

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

Uruchom:

```bash
local-shell-mcp --config /path/to/config.yaml
```

Environment variables z prefixem `LOCAL_SHELL_MCP_` nadpisują wartości YAML.

## Odpowiedzialność za host toolchain

Binary pakuje aplikację Python, ale nie wszystkie developer tools. MCP tools wywołują programy dostępne na host.

Zainstaluj to, czego potrzebują zadania:

| Capability | Host packages to consider |
|---|---|
| Search and shell ergonomics | `ripgrep`, `tree`, `jq`, `curl`, `wget`; Linux releases zawierają już static tmux helper |
| Git workflows | `git`, `gh`, OpenSSH client, credential helpers |
| Python projects | Python, pip, venv, project-specific compilers and headers |
| Node projects | Node.js, npm, pnpm, yarn |
| Rust/Go/Java/C++ | Cargo/rustc, Go, JDK, Maven/Gradle, compilers, CMake, Ninja |
| Browser automation | Playwright browser binaries and OS dependencies |
| Document conversion | LibreOffice, Pandoc, Poppler utilities |

Plik binarny zawiera Controller; zewnętrzne narzędzia i przeglądarki są opcjonalne. Chat i historia wymagają osobnego [web workspace](../getting-started/web-workspace.md) i bazy danych.

## Długotrwała usługa

Dla persistent public deployment uruchamiaj binary pod process supervisor systemu operacyjnego. Stosuj te zasady:

- Dedicated low-privilege OS account.
- Dedicated workspace directory.
- Sensitive values poza world-readable files.
- Automatyczny restart po failure.
- Kontrola `/healthz` po każdym restart.
- Dostępne logs do troubleshooting.

## Updates

1. Zastąp plik wykonywalny i uruchom Controller ponownie:
2. Opcjonalnie verify checksums.
3. Zastąp executable.
4. Restart process manager.
5. Sprawdź `/healthz`.
6. Przed dalszą pracą poproś client o `environment_get`.

## Uwagi o bezpieczeństwie

Binary działa z uprawnieniami użytkownika systemu operacyjnego. Dla public deployment używaj dedicated low-privilege user, dedicated workspace i w miarę możliwości VM/container boundary.

Nie ustawiaj `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` dla binary działającego bezpośrednio na personal host. To ustawienie jest przeznaczone dla disposable containers lub VM.
