<!-- i18n-source-sha256: cef0a90f9de3e2806e2a6bd8925217ea44ea6d6e6bce911eea09b1d4192a82d9 -->
# Opções de runtime e modelo de implantação

`local-shell-mcp` tem duas decisões complementares:

1. **Runtime**: como o processo do servidor roda e qual workspace controla.
2. **Interface**: use o [unified web workspace](../getting-started/web-workspace.md) opcional ou conecte um cliente MCP externo, como Gemini ou ChatGPT.

**Recomendamos o Controller como executável único**, sem Python, Docker ou código-fonte. As outras opções continuam disponíveis.

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

**Recomendado:** Para acesso público, implante em um servidor público ou encaminhe o tráfego por um servidor público com proxy reverso HTTPS. **Não recomendado:** O upload do lado do cliente via Cloudflare Tunnel pode ser muito lento, dificultando o envio e a transferência de arquivos. Use apenas se não houver opção de implantação ou encaminhamento por servidor público. ([Public HTTPS exposure](../clients/connectivity.md))

## Matriz de escolha de runtime

| Tempo de execução | Melhor para | Limite de isolamento | Fonte do conjunto de ferramentas | Acesso MCP externo | Página |
|---|---|---|---|---|---|
| **Executável único (recomendado)** | Maioria das plataformas suportadas | Host or VM | Ferramentas host mais executable configurado | Adicionar proxy HTTPS ou tunnel | [Standalone binary](../installation/binary.md) |
| Composição do Docker | Contêineres isolados e descartáveis | Recipiente | Imagem do Controlador Lean; instalar conjuntos de ferramentas específicos de tarefas separadamente | Adicionar proxy ou túnel HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + sidecar de túnel | Não recomendado: Encaminhe por servidor público; Cloudflare Tunnel apenas como último recurso | Recipiente | Imagem do projeto | Encaminhe por servidor público; Cloudflare Tunnel apenas como último recurso | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Iniciar/parar server de um editor workspace | Normalmente processo host | Ferramentas host mais executable configurado | Adicionar tunnel/proxy HTTPS externo para ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Fonte / pipx | Desenvolvimento e customização | Host virtualenv or VM | Pacote Python mais ferramentas host | Adicionar proxy HTTPS ou tunnel | [Python install](../installation/python.md) |
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

**Prefira o executável único**: baixe a versão correta e use uma conta restrita e workspace dedicado. [Guia do binário](../installation/binary.md).

Use a **extensão do VS Code** quando o fluxo de trabalho iniciar em um editor e você desejar um iniciador local. Ainda é um tempo de execução. Os clientes web remotos precisam de um proxy ou túnel HTTPS acessível.

**Código-fonte** é voltado a desenvolvimento, depuração e customização com Python virtual. [Guia Python](../installation/python.md).

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
