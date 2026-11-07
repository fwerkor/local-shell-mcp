<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# Início rápido

Este guia inicia um controlador LSM e abre sua interface do navegador. O [unified web workspace](web-workspace.md) é a experiência diária recomendada; é uma pilha de chat opcional implantada separadamente. ChatGPT, Gemini e outros clientes MCP externos podem se conectar ao mesmo controlador. Consulte [runtime choices and deployment model](../guides/deployment.md).

Recomendamos **implantar diretamente do código-fonte** em um ambiente isolado. Docker Compose é uma alternativa.

## Requisitos

- Git e Python 3.11+ com `venv` e `pip`.
- HTTPS público somente para usuários remotos ou clientes MCP externos.
- Diretório de trabalho dedicado e restrito.
- PIN de administrador OAuth forte e segredo JWT aleatório.

!!! warning
    O modelo conectado pode operar o workspace configurado. Execute o serviço em um container ou VM descartável e evite montar recursos de controle do host.

## 1. Clonar e configurar

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

Edite `.env` e substitua o PIN e segredo JWT de exemplo (use `openssl rand -hex 32`). A execução via código-fonte não carrega `.env` automaticamente.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Iniciar o servidor

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Verifique o status em outro terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

A resposta válida é HTTP `200`. Use um gerenciador de serviços para execução permanente.

## 3. Expor HTTPS

Para acesso remoto, use servidor público ou proxy reverso HTTPS (Caddy, Nginx, Traefik), encaminhando todo o site, inclusive uploads e downloads, para:

```text
http://127.0.0.1:8765
```

Verifique HTTPS:

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel não é recomendado** para arquivos: uploads do cliente podem ser lentos. Prefira servidor público ou proxy reverso/redirecionamento de portas com OAuth ativo. Alternativa: [Docker](../installation/docker.md).

## 4. Abra a área de trabalho do navegador

Abra o login do Controlador:

```text
https://your-public-host.example.com/ui
```

Para chat, projetos e páginas de controle integradas, siga o [unified web workspace guide](web-workspace.md). A WebUI leve e original está disponível quando o chat não está instalado.

## 5. Confirmar com segurança o acesso às ferramentas

Peça ao modelo:

```text
Use local-shell-mcp. Primeiro chame environment_get e depois liste a raiz do workspace. Não modifique arquivos ainda.
```

Ferramentas read-only esperadas:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Começar com uma tarefa de código limitada

Uma boa primeira tarefa:

```text
Inspecione este repository, resuma a estrutura do projeto, execute a suíte de testes existente se ela for óbvia e não altere arquivos.
```

Depois de confirmar a conectividade, forneça instruções mais específicas:

```text
Corrija o teste que está falhando. Leia primeiro os arquivos relevantes, faça o menor patch possível, execute o teste alvo e depois mostre git diff. Não faça commit até eu aprovar.
```

## Atualização

Atualize o código, reinstale o pacote editável e reinicie o Controller:

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

Para Docker Compose, atualize o contêiner:

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## Próximas páginas

| Necessidade | Página |
|---|---|
| Entender escolhas de runtime e client | [Opções de runtime e modelo de implantação](../guides/deployment.md) |
| Executar com Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Executar pelo VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Executar com um binary de release | [Runtime binary independente](../installation/binary.md) |
| Executar com Python ou source checkout | [Python runtimes](../installation/python.md) |
| Use o bate-papo unificado e a interface de controle | [Unified web workspace](web-workspace.md) |
| Adicionar Gemini Spark como cliente | [Gemini Custom Apps](gemini-spark.md) |
| Adicionar ChatGPT como client | [ChatGPT connector](chatgpt-connector.md) |
| Escolher ferramentas e escrever prompts melhores | [Padrões de uso](../guides/usage-patterns.md) |
| Conectar uma máquina HPC, NPU/GPU ou NAT | [Workers remotos](../guides/remote-workers.md) |
| Entender todas as ferramentas MCP | [Referência de ferramentas](../reference/tools.md) |
