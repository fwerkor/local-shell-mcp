<!-- i18n-source-sha256: 1d80cfbe14747fb0691e91065f582d1e47eb36921d8b27da1648dcd26114a2e5 -->
# Python, pipx 및 source runtimes

일반 배포에는 [단일 실행 파일](binary.md)을 권장합니다. Python과 소스 설치는 개발 및 사용자 지정에 적합합니다.

이 페이지는 세 가지 관련 경우를 다룹니다.

- `pipx install local-shell-mcp`: user-level executable install.
- `pip install local-shell-mcp`: 기존 virtual environment에 install.
- Editable source checkout: project 자체 개발 또는 디버깅.

## pipx install

일반 사용자에게 `pipx`는 가장 깔끔한 Python-based install입니다. command별 virtual environment를 제공하면서 executable을 `PATH`에 노출합니다.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

로컬 HTTP MCP server를 시작합니다.

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Health 확인:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Virtual environment install

Python environment를 직접 관리하는 경우 사용합니다.

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

process는 host에 설치된 tool을 사용합니다. Python package가 compiler, Git, browser system dependency 또는 project dependency를 대신 설치하지 않습니다.

## Editable source checkout

소스 설치는 개발용입니다. 일반 배포는 [단일 바이너리](binary.md)를 사용하고 OAuth/HTTPS는 [빠른 시작](../getting-started/quickstart.md)을 참고하세요.

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

검사 실행:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Browser setup

Playwright는 선택 사항입니다. 필요할 때만 라이브러리와 브라우저를 설치하세요.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

브라우저 설치는 선택 사항입니다. 기본 Docker 이미지에는 Playwright나 브라우저가 포함되지 않습니다.

## Public HTTP MCP use

ChatGPT 또는 다른 public HTTP MCP client에서 사용할 경우 다른 HTTP runtime과 같은 public-origin 및 OAuth 설정을 구성한 다음 local port를 reverse proxy 또는 tunnel로 공개합니다.

공개 MCP endpoint:

```text
https://your-public-host.example.com/mcp
```

## Development modes

| Mode | Command | 용도 |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | HTTPS 뒤의 ChatGPT를 포함한 HTTP 기반 전체 MCP client |
| REST-style HTTP | `local-shell-mcp --mode http` | 진단 또는 호환 endpoint; 주 ChatGPT 경로가 아님 |
| stdio | `local-shell-mcp --mode stdio` | process를 시작하는 로컬 MCP client |

`mode=both`는 예약되어 있으며 현재 단일 process mode로 사용하면 안 됩니다.

## Host-runtime safety

Python install은 VM/container에 넣지 않는 한 host user 권한으로 실행됩니다. workspace를 좁게 유지하고 full-container mode를 비활성화하며 workspace를 home directory로 지정하지 마십시오.

신뢰할 수 없는 repository, package-manager 사용이 많은 task 또는 host integration보다 resetability가 중요한 workflow에는 Docker Compose를 사용하십시오.
