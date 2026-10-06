<!-- i18n-source-sha256: e2dd23efea9768d971fa8a8be723f55cfcac3279adfc82e4185a803e3f05de1e -->
# Runtime Docker Compose

Docker Compose é o runtime recomendado para a maioria dos usuários. Ele oferece ao modelo um workspace Linux controlado, toolchain reproduzível, credenciais persistentes, suporte a browser automation e caminho simples de upgrade.

É uma escolha de runtime. Pode ser conectado ao ChatGPT, a um MCP client HTTP genérico ou mantido local para testes.

## O que a imagem Docker inclui

A imagem se baseia na imagem Python do Playwright e instala uma ampla toolchain de desenvolvimento. A ideia é permitir que um AI coding agent opere muitos repositories sem pedir para reconstruir o runtime para cada projeto.

Categorias incluídas:

| Categoria | Exemplos |
|---|---|
| Shell e inspeção | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git e credenciais | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| Outras linguagens | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Ferramentas de documentos | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

O conteúdo exato da imagem deve ser tratado como camada de conveniência, não API estável. Dependências específicas do projeto continuam pertencendo ao workspace ou scripts de build.

## Execução local básica

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

O token local gerado fica no `.env` pertencente ao host (modo `0600`) e é passado ao contêiner pelo Compose. Assim, `lsm call` no host pode autenticar no loopback controller sem ler estado pertencente ao contêiner.

O Compose file padrão vincula o serviço a localhost:

```text
127.0.0.1:8765 -> container:8765
```

Isso é apropriado para testes locais e para reverse proxy no mesmo host.

## Layout do workspace

O runtime Compose padrão monta:

| Path ou volume host | Path container | Finalidade |
|---|---|---|
| `./workspaces/default` | `/workspace` | Workspace controlado visível para tools |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Estado persistente de credenciais Git/GitHub/SSH/GPG |

Use um diretório de workspace por trust boundary. Não monte todo o home directory apenas por conveniência.

## Configurações públicas obrigatórias

Para ChatGPT ou outro MCP client HTTP público, configure `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Gere um JWT secret com um comando como:

```bash
openssl rand -hex 32
```

A URL MCP pública é:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

O Compose file inclui serviço `cloudflared` opcional atrás do profile `tunnel`. Isso executa o tunnel ao lado do MCP server.

Configure `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Inicie os dois serviços:

```bash
docker compose --profile tunnel up -d
```

No Cloudflare Zero Trust, roteie o public hostname para:

```text
http://local-shell-mcp:8765
```

Isso é Cloudflare Tunnel, não Cloudflare Access. `local-shell-mcp` continua tratando o próprio OAuth do ChatGPT.
O serviço Compose confia em forwarded headers porque sua porta publicada fica restrita a localhost; isso preserva o endereço público do caller para rate limiting do OAuth PIN. Se expuser a porta do container diretamente, substitua `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` pelos endereços explícitos de reverse proxies confiáveis.

## Reverse proxy sem tunnel sidecar

Se já usa Caddy, Nginx, Traefik ou Nginx Proxy Manager, mantenha o serviço Compose normal e encaminhe HTTPS para:

```text
http://127.0.0.1:8765
```

O proxy deve encaminhar estas routes sem remover paths:

| Route | Finalidade |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/oauth-protected-resource` | OAuth resource metadata |
| `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata |
| `/oauth/register` | Dynamic client registration |
| `/oauth/authorize` | Browser authorization page |
| `/oauth/token` | Token exchange |
| `/downloads/<token>` | Optional generated file downloads |
| `/join/<token>`, `/remote/*` | Optional remote-worker bootstrap / polling |

Consulte [network connectivity](../clients/connectivity.md) para requisitos de comportamento do proxy.

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` mantém operações de filesystem limitadas ao workspace. É o default mais seguro.

Defina `true` somente quando o container for deliberadamente disposable e se espera que o modelo opere todo o filesystem do container. Ao ativar, restrições built-in de command/path denylist são removidas.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Não ative full-container mode em runtime iniciado diretamente no host, como VS Code extension ou binary rodando no notebook.

## Credenciais

O runtime Docker pode persistir credenciais comuns de desenvolvimento em volume dedicado. É útil para GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config e estado GPG.

Trate o volume de credenciais como sensível. Prefira deploy keys por repository, tokens fine-grained ou credenciais de curta duração. Não coloque credenciais pessoais amplas em workspace que o modelo possa ler livremente.

SSH-agent forwarding é possível montando o socket do agente, mas estende confiança do container para seu agente ativo. Use apenas se entender a exposição.

## Atualizações

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Com tunnel sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Depois do upgrade, peça primeiro um check read-only ao client:

```text
Use local-shell-mcp. Chame environment_get e file_list na raiz do workspace. Não modifique arquivos.
```

## Solução de problemas

| Sintoma | Verificar |
|---|---|
| `/healthz` falha localmente | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT não descobre tools | URL pública deve terminar em `/mcp`; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` não deve incluir `/mcp` |
| Página OAuth falha | Admin PIN e JWT secret devem estar definidos para deployments OAuth públicos |
| Tools não veem arquivos | Confirme que o diretório host pretendido está montado em `/workspace` |
| Browser tools falham | Confirme que a imagem Playwright está atualizada; tente `run_shell` para o browser alvo |
| Git auth desapareceu | Verifique o volume de credenciais e se o container recriado usa o mesmo volume |
