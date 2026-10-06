<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# Interface humana

`local-shell-mcp` oferece duas interfaces humanas compatíveis sobre a mesma API de serviço, workspace, registro de terminais persistentes, registro de workers remotos e log de auditoria MCP:

- **Web UI** é um painel nativo do navegador otimizado para inspeção operacional rápida.
- **OpenTUI** é o aplicativo completo orientado a terminal e continua disponível tanto no navegador quanto como comando nativo de terminal.

Nenhum modo cria um control plane separado. Trocar de interface não altera máquinas conectadas, Sessions, jobs, permissões ou dados de auditoria.

## Iniciar o serviço

Inicie `local-shell-mcp` normalmente:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

Quando o ChatGPT renderiza MCP Apps, `workspace_open(session_id=...)` abre uma visão colaborativa flutuante da **Logical Session selecionada explicitamente**. A Session mantém o estado durável da tarefa — objective, progress, Plan e Activity — enquanto o Live Workspace apenas apresenta esse estado, a atividade ao vivo e os controles humanos. Ele nunca infere a identidade da tarefa a partir do transporte MCP.

Um handoff explícito típico é:

```text
session_manage(action="start", objective=...)
        -> session_id
... chamadas de ferramentas com logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
nova conversa do ChatGPT
o usuário passa o session_id anterior
session_manage(action="resume", session_id=...)
        -> progress, Plan e Activity recente existentes
workspace_open(session_id=...)
        -> visão da mesma Session
```

`session_id` é a única identidade durável da tarefa. Um agent não deve listar, inferir nem selecionar automaticamente uma Session de outra conversa. Para continuar o trabalho em uma nova conversa, o usuário passa explicitamente o `session_id` existente. O agent deve informar o `session_id` ativo após start/resume, em checkpoints relevantes de progresso e antes de encerrar um turn, permitindo handoff manual. Sessions não ficam vinculadas a uma machine nem a um working directory; parâmetros normais das ferramentas continuam escolhendo targets locais/remotos e paths.

Um Plan opcional de `plan_manage` habilita o Goal mode da Session. Se o Plan estiver active e não houver agent activity por 15 minutos, um Live Workspace associado pode pedir ao ChatGPT para continuar. A continuation retoma o mesmo `session_id` explícito e é limitada a 10 tentativas, aceitas ou rejeitadas. Plans blocked, completed e cancelled não são continuados automaticamente; um Plan active cujos steps estejam todos completed ou skipped continua elegível a uma continuation de encerramento para que o agent retomado possa finalizar o Plan. Os controles humanos pause/resume/cancel atualizam o Plan pertencente à Session, e não um estado efêmero do Live Workspace.

## Interface do navegador

Abra:

```text
http://127.0.0.1:8765/ui
```

Para uma implantação pública, use o origin HTTPS configurado:

```text
https://your-public-host.example.com/ui
```

A interface do navegador usa o mesmo servidor OAuth e os mesmos scopes que o MCP. O shell da página e os recursos estáticos são públicos para que a tela de login possa carregar, enquanto `/api/ui/*` e o WebSocket de terminal do OpenTUI permanecem protegidos. Tokens de acesso ficam apenas no session storage do navegador.

### Escolher uma interface

A tela OAuth oferece duas entradas:

- **Open Web UI** autoriza e abre o painel nativo.
- **Continue to OpenTUI** autoriza e abre a interface de terminal, preservando o comportamento anterior do navegador.

Após a autorização, o seletor na barra lateral alterna entre Web UI e OpenTUI sem novo login. A página nativa atual é lembrada ao mudar temporariamente para OpenTUI.

As rotas podem ser adicionadas aos favoritos:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` e `#/dashboard` são aliases de Overview. `#/tui` e `#/opentui` são aliases de Console.

## Web UI nativa

A Web UI nativa consulta a API de interface humana existente a cada cinco segundos e renderiza controles nativos do navegador em vez de células de terminal. Nenhum PTY é iniciado até OpenTUI ser selecionado.

### Overview

Overview mostra primeiro as informações operacionais de maior prioridade:

- Saúde do controller e versão atual do LSM.
- Contagem de máquinas online e offline.
- Tracked jobs ativos e sessões persistentes de terminal.
- CPU, memória, disco do workspace, load, throughput de rede e uptime.
- Alertas gerados pelo estado de workers, limites de recursos, jobs com falha e chamadas MCP com falha.
- Atividade MCP recente originada pelo modelo.

### Machines

Machines lista o controller local e os workers remotos conectados com status, plataforma, versão, diretório de trabalho, capacidades e informações de last-seen.

### Workloads

Workloads combina tracked jobs ativos e sessões shell persistentes independentes. A Web UI é somente leitura para esses registros; use OpenTUI para gerenciamento interativo de sessões.

### Activity

Activity combina alertas atuais e atividade recente de auditoria MCP. Comandos digitados por humanos e operações de arquivos permanecem fora do log de auditoria MCP.

## OpenTUI no navegador

Selecionar **OpenTUI** inicia sob demanda o mesmo aplicativo OpenTUI usado pelo launcher de terminal nativo. O console do navegador mantém:

- Transporte PTY binário autenticado via WebSocket.
- Redimensionamento automático do terminal e backoff de reconexão.
- Interação por mouse com controles OpenTUI.
- Modo tela cheia e atalhos de teclado seguros para o navegador.
- Teclas de atalho móveis e controle explícito do teclado virtual.
- Suporte a SIXEL e inline image por xterm.js.

O navegador não cria um PTY OpenTUI enquanto o usuário permanecer no modo Web UI nativo.

## OpenTUI nativo

Executáveis release independentes incorporam o runtime OpenTUI da plataforma. Mantenha apenas o executável principal, inicie o serviço e execute:

```bash
local-shell-mcp tui
```

O TUI nativo não pede login ao operador humano. Na configuração Docker Compose documentada, o launcher reutiliza a credencial CLI dedicada mantida somente no host para a Human UI API via loopback; outros layouts split-runtime podem usar `--token-file`. Instâncias do OpenTUI iniciadas pelo navegador usam uma credencial do processo do controller, criada sob demanda e nunca persistida no state directory ou no state backend. Um proxy reverso não recebe nenhum desses bypasses locais apenas por se conectar via loopback.

Um checkout do código-fonte também pode executar o TUI depois de instalar as dependências Bun:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

Use `--api-base` somente quando o serviço local usar uma porta diferente da padrão:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## Telas do OpenTUI

### Dashboard

Dashboard é a visão operacional do OpenTUI. Terminais largos mostram regiões separadas para node, workload, alert, activity, informações do sistema e tendências; terminais menores recolhem tudo em resumos compactos sem rolagem horizontal.

### Files

Files é um gerenciador de arquivos nativo do LSM com três painéis para máquinas locais e remotas. Ele oferece criar, editar, renomear, copiar, mover, colar, excluir, alternar arquivos ocultos, atualizar, pré-visualizar texto, pré-visualizar binários e miniaturas de imagens limitadas.

### Terminals

Terminals gerencia sessões shell persistentes em máquinas locais e remotas. Suporta entrada de comandos completos, entrada interativa raw, troca de sessão, criação e encerramento de sessões, saída recente e um painel de auditoria MCP recolhível.

### Audit

Audit lê o log de auditoria JSONL limitado e oferece filtros node, operation, event, session, search, time-range e sort, além de inspeção detalhada dos registros.

### Remotes

Remotes mostra workers remotos online e offline, capacidades, diretórios de trabalho e metadados do sistema. Pode criar um join invite de uso único, renomear um node ou revogar sua identidade persistente.

## Navegação do OpenTUI

A barra superior de categorias e as ações contextuais do rodapé podem ser clicadas com o mouse em terminais nativos e no console do navegador.

| Teclas | Ação |
|---|---|
| `Alt+1` … `Alt+5` | Abre Dashboard, Files, Terminals, Remotes ou Audit. |
| `F2` … `F6` | Atalhos alternativos de categoria. |
| `F1` | Abrir o guia de teclado. |
| `F9` | Atualizar a lista de máquinas. |
| `Alt+Q` | Sair do processo OpenTUI nativo sem invocar um atalho Ctrl reservado pelo navegador. |

Terminals usa `Alt+N` para nova sessão, `Alt+W` para encerrar a sessão selecionada, `Alt+A` para alternar o painel de auditoria, `Alt+R` para atualizar e `Alt+Left/Right` para trocar de sessão. O console do navegador intercepta essas combinações antes da navegação ou menus do navegador.

## Configuração

| Chave YAML | Variável de ambiente | Padrão | Finalidade |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Montar ou desativar as interfaces humanas. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | Caminho de montagem da interface do navegador no serviço MCP. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Substituir a resolução do executável OpenTUI nativo. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | Configuração de papel de parede mantida para implantações do console OpenTUI no navegador. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Fechar um PTY OpenTUI inativo do navegador após estes segundos; `0` desativa o timeout. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Máximo de sessões PTY OpenTUI simultâneas no navegador. |

## Notas de empacotamento

- Imagens Docker incluem os recursos da Web UI e o runtime OpenTUI nativo.
- Executáveis independentes incorporam os recursos da Web UI e um runtime OpenTUI de plataforma compactado.
- Wheels Python incluem os recursos do navegador; OpenTUI nativo exige um executável release ou checkout do código-fonte com dependências Bun instaladas.
- As duas interfaces são servidas pelo mesmo processo e porta do MCP; nenhum serviço web adicional é necessário.
