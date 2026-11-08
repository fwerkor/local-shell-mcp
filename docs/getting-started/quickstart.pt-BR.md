<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Início rápido

Este guia inicia um controlador LSM e abre sua interface do navegador. O [unified web workspace](web-workspace.md) é a experiência diária recomendada; é uma pilha de chat opcional implantada separadamente. ChatGPT, Gemini e outros clientes MCP externos podem se conectar ao mesmo controlador. Consulte [runtime choices and deployment model](../guides/deployment.md).

Recomendamos o **executável único do Controller** do [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest), sem Python, Docker ou checkout do código. Exemplo para **Linux x86_64**; outras plataformas: [binários](../installation/binary.md).

## Requisitos

- Executável compatível e `curl` (exemplo Linux x86_64).
- HTTPS público apenas para usuários remotos ou clientes MCP externos.
- Workspace dedicado e restrito.
- PIN de administrador OAuth forte e segredo JWT aleatório.

!!! warning
    O modelo conectado pode operar o workspace configurado. Execute o serviço em um container ou VM descartável e evite montar recursos de controle do host.

## 1. Baixar o executável e configurar

Baixe o executável único e gere o segredo JWT:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

Crie `.env` e substitua o PIN e o segredo JWT de exemplo (use `openssl rand -hex 32`). O binário **não carrega automaticamente** `.env`.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Iniciar o servidor

Execute diretamente o binário:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Verifique o status em outro terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Uma resposta válida retorna HTTP `200`. Para operação contínua, use um supervisor e uma conta restrita.

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

Substitua o executável e reinicie o Controller:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Para Docker Compose, atualize o contêiner; para código fonte, veja [Python](../installation/python.md).

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
