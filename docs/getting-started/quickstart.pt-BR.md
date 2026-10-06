<!-- i18n-source-sha256: 51bfe29de540492ab1da2df9479464641bb335796b0538357235fac5b4a2e446 -->
# Início rápido

Este guia usa Docker Compose como primeiro runtime e ChatGPT como primeiro client. São escolhas independentes: Docker, VS Code extension, binary, Python e stdio são opções de runtime; ChatGPT e clientes MCP genéricos são opções de client. Consulte [opções de runtime e modelo de implantação](../guides/deployment.md) para o mapa completo.

## Requisitos

- Docker Engine com Compose v2.
- Um endpoint HTTPS público se o ChatGPT precisar se conectar pela Web.
- Um diretório de workspace dedicado.
- Um OAuth admin PIN e JWT secret longos e aleatórios.

!!! warning
    O modelo conectado pode operar o workspace configurado. Execute o serviço em um container ou VM descartável e evite montar recursos de controle do host.

## 1. Clonar e configurar

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
```

Edite `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. Iniciar o servidor

```bash
mkdir -p workspaces/default
docker compose up -d
```

Verifique o status:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Uma resposta saudável retorna HTTP `200`.

## 3. Expor HTTPS

Para o sidecar do Cloudflare Tunnel:

```bash
docker compose --profile tunnel up -d
```

No Cloudflare Zero Trust, aponte o public hostname para:

```text
http://local-shell-mcp:8765
```

Com Caddy, Nginx, Traefik, Nginx Proxy Manager ou outro reverse proxy, encaminhe o tráfego HTTPS para `127.0.0.1:8765` ou para o endereço de rede do container.

## 4. Conectar o ChatGPT

Use o endpoint MCP:

```text
https://your-public-host.example.com/mcp
```

Siga o [guia do conector ChatGPT](chatgpt-connector.md) para concluir OAuth e aprovação das ferramentas.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Se você usa o perfil tunnel:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
| Adicionar ChatGPT como client | [ChatGPT connector](chatgpt-connector.md) |
| Escolher ferramentas e escrever prompts melhores | [Padrões de uso](../guides/usage-patterns.md) |
| Conectar uma máquina HPC, NPU/GPU ou NAT | [Workers remotos](../guides/remote-workers.md) |
| Entender todas as ferramentas MCP | [Referência de ferramentas](../reference/tools.md) |
