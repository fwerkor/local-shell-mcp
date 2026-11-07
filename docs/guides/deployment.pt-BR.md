<!-- i18n-source-sha256: 594169d44520f8abd7cebee1bfa42c5ff0ca31f424115d438107ed01b77fa604 -->
# Opções de runtime e modelo de implantação

`local-shell-mcp` tem duas decisões complementares:

1. **Runtime**: como o processo do servidor roda e qual workspace controla.
2. **Interface**: use o [unified web workspace](../getting-started/web-workspace.md) opcional ou conecte um cliente MCP externo, como Gemini ou ChatGPT.

A interface diária recomendada é o espaço de trabalho web auto-hospedado (chat, projetos e páginas de controle LSM). Ele é implantado separadamente do Controlador. Docker, a extensão VS Code, binários de lançamento, instalações Python e modo stdio são maneiras de executar o Controlador; aplicativos de bate-papo externos permanecem clientes opcionais.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Compose apenas HTTP local Espaço de trabalho unificado da web
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Uma configuração auto-hospedada comum é:

```text
Navegador -> https://chat.example.com (espaço de trabalho web unificado)
        -> Controlador local-shell-mcp autenticado
        -> espaço de trabalho controlado e trabalhadores de saída
Cliente externo opcional -> https://mcp.example.com/mcp
```

Uma configuração de MCP client local pode ser mais simples:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

## Matriz de escolha de runtime

| Tempo de execução | Melhor para | Limite de isolamento | Fonte do conjunto de ferramentas | Acesso MCP externo | Página |
|---|---|---|---|---|---|
| Composição do Docker | A maioria das cargas de trabalho do agente de codificação e espaços de trabalho repetíveis | Recipiente | Imagem do Controlador Lean; instalar conjuntos de ferramentas específicos de tarefas separadamente | Adicionar proxy ou túnel HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + sidecar de túnel | Implantação de controlador público com Cloudflare Tunnel | Recipiente | Imagem do projeto | Integrado ao perfil `tunnel` do Compose | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Iniciar/parar server de um editor workspace | Normalmente processo host | Ferramentas host mais executable configurado | Adicionar tunnel/proxy HTTPS externo para ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Hosts ou VM sem Docker | Host or VM | Ferramentas host mais executable configurado | Adicionar proxy HTTPS ou tunnel | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Uso Python-native, debugging, development | Host virtualenv or VM | Pacote Python mais ferramentas host | Adicionar proxy HTTPS ou tunnel | [Python install](../installation/python.md) |
| Stdio mode | MCP clients locais que iniciam processos diretamente | Client process boundary | Ferramentas host mais executable configurado | Não utilizável pelo ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Matriz de conexão client

| Interface | Requer HTTPS público | Usa `/mcp` | Requer OAuth | Tempo de execução típico |
|---|---:|---:|---:|---|
| Espaço de trabalho web unificado do LSM | Sim para acesso remoto; proxy local também é possível | Internamente | Login do LSM | Controlador mais pilha web separada |
| Gemini Spark / Aplicativos personalizados | Sim | Sim | Sim, para uso público | Qualquer controlador HTTP |
| ChatGPT custom MCP connector | Sim | Sim | Sim para uso público | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | Não | Não | Não | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Normalmente não em localhost; sim entre redes | Sim | Recomendado fora de localhost | Any HTTP runtime |
| VS Code extension helper flow | Somente se ChatGPT precisar conectar | Sim ao copiar URL ChatGPT | Recomendado para ChatGPT | VS Code-launched runtime |

Consulte [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) e [network connectivity](../clients/connectivity.md).

## O que cada runtime controla

Todo runtime inicia o mesmo código de servidor e expõe as mesmas famílias de MCP tools quando habilitadas:

- Shell e persistent shell sessions.
- Filesystem, search e patch tools.
- Operações Git.
- Browser automation via Playwright.
- Audit log e task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle e machine-routed tools.

A diferença não é a API abstrata, mas o **operating environment** por trás dela.

| Pergunta | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Onde os comandos rodam? | Dentro do container | Normalmente no host workspace | No process environment do host ou VM |
| Default workspace? | Mounted `/workspace` | Pasta VS Code atual ou path configurado | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Os compiladores e navegadores estão pré-instalados? | Não; instale o que a tarefa precisa | Somente se instalado no host | Somente se instalado no host |
| É fácil resetar? | Recriar container e volume workspace | Depende do workspace | Depende do host/VM |
| Adequado para installs arbitrários? | Sim, se disposable | Mais arriscado no host | Mais arriscado fora de VM |

## Seleção recomendada

Use **Docker Compose** primeiro, a menos que tenha um motivo para não fazê-lo. Ele fornece um limite de segurança claro sem exigir um grande conjunto de ferramentas de desenvolvimento pré-instalado.

Use a **extensão do VS Code** quando o fluxo de trabalho iniciar em um editor e você desejar um iniciador local. Ainda é um tempo de execução. Os clientes web remotos precisam de um proxy ou túnel HTTPS acessível.

Use **standalone binary** quando Docker não estiver disponível, mas VM, container host ou conta dedicada já fornecerem a boundary.

Use **`pipx` ou source install** para development/debugging do próprio `local-shell-mcp` ou quando um Python-based environment for mais fácil de manter.

Use **stdio mode** somente para MCP clients locais que possam spawn o server process. Não é deployment público nem utilizável diretamente pelo ChatGPT web/app.

## Regra do endpoint público

Para clientes HTTP MCP externos, como Gemini e ChatGPT, o endpoint MCP é:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` é apenas o origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Não acrescente `/mcp` a `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Páginas de runtime

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Páginas de client

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
