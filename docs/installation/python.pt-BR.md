<!-- i18n-source-sha256: c8c0d8ebdbb123b9ac4af1fd288f30e8ca69037ca086486cb8027e2592f4b75a -->
# Runtimes Python, pipx e source

**A instalação direta do repositório fonte é recomendada.** Use um ambiente virtual Python e um workspace restrito. Docker Compose continua disponível.

Use esta página para três casos relacionados:

- `pipx install local-shell-mcp`: instalação de executable no nível do usuário.
- `pip install local-shell-mcp`: instalação em um virtual environment existente.
- Editable source checkout: desenvolver ou depurar o próprio projeto.

## Instalação com pipx

`pipx` é a instalação baseada em Python mais limpa para usuários comuns, pois dá ao comando seu próprio virtual environment enquanto expõe um executable no `PATH`.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Inicie um servidor MCP HTTP local:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Verifique a integridade:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Instalação em virtual environment

Use quando já gerencia ambientes Python manualmente:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

O process usa as ferramentas instaladas no host. O pacote Python não instala compiladores, Git, dependências de sistema do navegador ou dependências do projeto para você.

## Editable source checkout

Use para implantação normal e desenvolvimento. Para acesso público, consulte [quickstart](../getting-started/quickstart.md).

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

Execute as verificações:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Configuração do navegador

Playwright é opcional; instale a biblioteca e o navegador quando precisar.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

Instalar navegador é opcional; a imagem Docker básica não traz Playwright ou navegadores.

## Uso público de HTTP MCP

Para ChatGPT ou outro public HTTP MCP client, configure o mesmo public origin e OAuth dos demais runtimes HTTP e exponha a porta local por reverse proxy ou tunnel.

O endpoint MCP público é:

```text
https://your-public-host.example.com/mcp
```

## Modos de desenvolvimento

| Mode | Command | Uso |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | MCP clients completos via HTTP, incluindo ChatGPT atrás de HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Endpoints de diagnóstico ou compatibilidade, não o caminho principal do ChatGPT |
| stdio | `local-shell-mcp --mode stdio` | MCP clients locais que iniciam o process |

`mode=both` é reservado e atualmente não deve ser usado como mode de um único process.

## Segurança do host runtime

Instalações Python executam como seu host user, a menos que sejam colocadas em VM/container. Mantenha o workspace restrito, full-container mode desativado e não aponte o workspace para um home directory.

Use Docker Compose para repositories não confiáveis, tarefas intensivas em package manager ou workflows em que resetability importa mais que integração com o host.
