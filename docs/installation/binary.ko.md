<!-- i18n-source-sha256: ed47d5e0691f17af5cd4758981c31957e299202bf72433b34b4656346312091e -->
# Standalone binary runtime

GitHub Releases의 **Controller 단일 실행 파일** 배포를 권장합니다. Python, Docker, 소스 체크아웃이 필요 없습니다.

이는 runtime 선택입니다. ChatGPT access는 HTTPS `/mcp` endpoint를 통해 별도로 구성합니다.

## Release artifacts

GitHub Releases는 일반 platform용 self-contained executable을 build합니다.

| Platform artifact | Archive |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

각 archive에는 executable, README, license, 짧은 quickstart file이 포함됩니다.

**단일 실행 파일**도 배포됩니다. Controller와 기본 WebUI만 포함하며 채팅, 데이터베이스, Worker, 개발 도구 및 브라우저는 별도 구성입니다.

## Install

1. [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest)에서 플랫폼에 맞는 실행 파일 또는 압축 파일을 다운로드하세요.
2. 압축 파일을 선택했다면 압축을 해제하세요.
3. executable을 `PATH`에 두거나 absolute path를 기록합니다.
4. `local-shell-mcp --help`를 실행해 binary가 시작되는지 확인합니다.

예시: Linux x86_64 단일 파일을 직접 다운로드합니다. 다른 플랫폼은 호환 파일을 선택하세요:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
```

Windows 사용자는 PowerShell에서 `local-shell-mcp.exe`를 실행하거나 해당 directory를 `PATH`에 설정하십시오.

## Minimal local run

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
~/lsm/local-shell-mcp --mode mcp
```

다른 terminal에서:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Public HTTP MCP run

ChatGPT 또는 public HTTP MCP client에서 사용할 경우 다음 설정 범주를 지정합니다.

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | tool이 제어하는 directory |
| `LOCAL_SHELL_MCP_HOST` and `LOCAL_SHELL_MCP_PORT` | local bind address 및 port |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `/mcp`가 없는 public HTTPS origin |
| `LOCAL_SHELL_MCP_AUTH_MODE` | public deployment에서는 `oauth` 사용 |
| OAuth PIN and JWT secret settings | public OAuth authorization에 필요 |

local HTTP port를 reverse proxy 또는 tunnel로 공개합니다. public endpoint:

```text
https://your-public-host.example.com/mcp
```

## YAML config

secret이 아닌 runtime default를 YAML config에 저장할 수 있습니다.

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

실행:

```bash
local-shell-mcp --config /path/to/config.yaml
```

`LOCAL_SHELL_MCP_` prefix의 environment variable은 YAML value를 덮어씁니다.

## Host toolchain responsibility

binary는 Python application을 package하지만 모든 developer tool을 포함하지는 않습니다. MCP tool은 host에서 사용 가능한 program을 호출합니다.

작업에 필요한 항목을 설치하십시오.

| Capability | Host packages to consider |
|---|---|
| Search and shell ergonomics | `ripgrep`, `tree`, `jq`, `curl`, `wget`; Linux release에는 static tmux helper 포함 |
| Git workflows | `git`, `gh`, OpenSSH client, credential helpers |
| Python projects | Python, pip, venv, project-specific compilers and headers |
| Node projects | Node.js, npm, pnpm, yarn |
| Rust/Go/Java/C++ | Cargo/rustc, Go, JDK, Maven/Gradle, compilers, CMake, Ninja |
| Browser automation | Playwright browser binaries and OS dependencies |
| Document conversion | LibreOffice, Pandoc, Poppler utilities |

바이너리에는 Controller만 포함됩니다. 외부 도구와 브라우저는 필요할 때 설치하세요. 채팅 및 기록은 별도 [웹 워크스페이스](../getting-started/web-workspace.md)와 데이터베이스가 필요합니다.

## Long-running service

persistent public deployment에서는 OS process supervisor 아래에서 binary를 실행하십시오. 다음을 지키십시오.

- dedicated low-privilege OS account 사용.
- dedicated workspace directory 사용.
- sensitive value를 world-readable file 밖에 저장.
- failure 시 자동 restart.
- restart 후마다 `/healthz` 확인.
- troubleshooting용 log 유지.

## Updates

1. 새 실행 파일로 교체한 뒤 Controller를 다시 시작하세요:
2. 필요하면 checksum을 verify합니다.
3. executable을 교체합니다.
4. process manager를 restart합니다.
5. `/healthz`를 확인합니다.
6. 작업을 계속하기 전에 client에서 `environment_get`를 실행합니다.

## Safety notes

binary는 OS user의 권한으로 실행됩니다. public deployment에는 dedicated low-privilege user, dedicated workspace, 가능하면 VM/container boundary를 사용하십시오.

personal host에서 직접 실행하는 binary에 `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true`를 설정하지 마십시오. 이 설정은 disposable container/VM용입니다.
