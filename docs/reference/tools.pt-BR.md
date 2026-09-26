<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Referência de ferramentas

Esta página é construída a partir dos schemas MCP reais. Execute `python scripts/generate-tools-reference.py` após alterar a superfície pública de tools para atualizar a referência English.

A maioria das ferramentas retorna um `ToolResult` estruturado com `ok`, `message` e `data`. `workspace_open` retorna o estado visível ao modelo usado para renderizar a MCP App. A maioria das ferramentas de execução e arquivos aceita `machine` opcional: omita para o workspace do controller e informe para um worker conectado. Operações Git usam deliberadamente `run_shell` ou outra ferramenta shell, em vez de wrappers Git dedicados.

## Guia de seleção

| Necessidade | Tools preferidas |
|---|---|
| Monitorar ou colaborar com a execução no ChatGPT | `workspace_open` |
| Inspecionar um ambiente | `environment_get`, `file_tree`, `file_read` |
| Executar command curto ou operação Git | `run_shell` |
| Executar tarefa interativa ou longa | `shell_start` or `job_start` |
| Fazer mudanças exatas em arquivos | `file_edit` or `file_patch` |
| Transferir arquivo ou diretório | `remote_transfer` |
| Descobrir capability MCP externa | `mcp_tool_search`, then `mcp_tool_inspect` |
| Interagir com uma página | `browser_session`, `browser_snapshot`, then `browser_act` |
| Executar lógica browser personalizada | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Trabalhar em máquina remota | use a mesma tool com `machine`; use `remote_*` apenas para administração de workers |

## Workspace interativo

### `workspace_open`

Abre ou reutiliza um Live Workspace que exibe a Logical Session informada explicitamente. Passe o session_id ativo retornado por session_manage. O Workspace nunca infere a identidade da tarefa a partir do transporte MCP; passe null explicitamente quando não houver Logical Session ativa.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

## Ambiente, Skills e estado de tarefas

### `environment_get`

Retorna versão, workspace, auth, policy e informações de ambiente localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `skill_list`

Lista Agent Skills instaladas sem carregar suas instructions. A superfície MCP de tools permanece fixa; adicionar ou remover diretórios Skill aparece na próxima chamada.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

Carrega uma Skill instalada pelo nome exato retornado por `skill_list`. Retorna instructions completas de `SKILL.md` e paths de arquivos relacionados.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Lê um arquivo de texto relacionado de uma Skill instalada.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Escaneia arquivos de texto do workspace local em busca de secrets comuns antes de commit ou push.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Gerencia uma única Logical Session durável. start cria uma nova tarefa e retorna seu session_id. resume continua somente o session_id explícito fornecido pelo usuário ou já presente nesta conversa. Todas as ações, exceto start, exigem session_id. Ações: start, resume, get, report, finish, cancel, delete. report aceita summary/findings/next/blockers/objective/label; delete exige uma Session terminal.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `label` | `string \| null` | `null` |  |
| `objective` | `string \| null` | `null` |  |
| `summary` | `string \| null` | `null` |  |
| `findings` | `array[string] \| null` | `null` |  |
| `next` | `string \| null` | `null` |  |
| `blockers` | `array[string] \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `plan_manage`

Gerencia o Goal mode opcional da Logical Session explícita. Um plan ativo habilita continuação automática após 15 minutos sem atividade do agent, limitada a 10 tentativas. session_id deve ser o mesmo id durável retornado por session_manage. Ações: start, get, update, block, resume, finish, cancel. start exige objective e steps; finish exige todos os steps completed ou skipped.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string` | required |  |
| `objective` | `string \| null` | `null` |  |
| `steps` | `array[object] \| null` | `null` |  |
| `step_id` | `string \| null` | `null` |  |
| `status` | `string \| null` | `null` |  |
| `text` | `string \| null` | `null` |  |
| `note` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `audit_tail`

Lê entradas recentes do audit log local.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells e jobs

### `run_shell`

Executa um command shell não interativo localmente ou em máquina remota. Use para build, test, package-manager, Git e inspeção que devam terminar rapidamente. Para processos longos, interativos ou streaming, use `shell_start` ou `job_start`. Campos opcionais purpose/explanation permitem indicar por que o command está sendo executado.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `run_python`

Escreve e executa um script Python curto localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `shell_start`

Inicia shell interativo persistente localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `shell_send`

Envia input para sessão shell persistente local ou remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `shell_read`

Lê output recente de sessão shell persistente local ou remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `shell_stop`

Encerra sessão shell persistente local ou remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `shell_list`

Lista sessões shell persistentes localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `job_start`

Inicia job longo e trackeado localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `job_list`

Lista jobs trackeados localmente ou em máquina remota. Jobs ativos são retornados primeiro; `limit` é limitado ao intervalo de 1-1000.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `job_tail`

Lê output recente de job local ou remoto trackeado.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `job_stop`

Para job local ou remoto trackeado.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `job_retry`

Reinicia job local ou remoto trackeado que foi parado ou saiu.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

## Arquivos e transferências

### `file_list`

Lista arquivos e diretórios localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `file_tree`

Retorna árvore compacta de diretórios localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `file_glob`

Encontra paths por glob localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `file_grep`

Pesquisa conteúdo de arquivos localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `file_read`

Lê um arquivo ou lista de arquivos localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `image_view`

Exibe PNG, JPEG, GIF ou WebP como conteúdo de imagem MCP nativo localmente ou em máquina remota. Use em vez de `file_read` quando inspeção visual for necessária. Imagens remotas reutilizam o protocolo de transferência existente, então o worker não precisa de RPC específico de imagem.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `file_write`

Escreve arquivo de texto UTF-8 localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `file_edit`

Aplica um ou mais edits de texto exatos a um arquivo local ou remoto. Cada edit contém old, new e `replace_all` opcional; old deve corresponder exatamente, incluindo whitespace e indentation.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `file_delete`

Exclui arquivo ou diretório local ou remoto. `recursive=false` exclui arquivos ou diretórios vazios; diretórios não vazios exigem `recursive=true`, que deve ser usado com cuidado.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `file_patch`

Verifica e aplica unified diff ou envelope file_patch local ou remotamente.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `remote_transfer`

Inicia um job rastreado que copia um arquivo ou diretório entre o controller e máquinas remotas. Uploads remotos usam chunks raw-binary retomáveis; gerencie a transferência com `job_list`, `job_tail`, `job_stop` e `job_retry`.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Pelo menos um de `source_machine` e `destination_machine` deve ser informado. Endpoints omitidos referem-se ao workspace do controller; a origem pode ser arquivo ou diretório.

### `link_create`

Cria URL temporária acessível por browser para arquivo local. Por default a resposta baixa como attachment; defina `inline=true` para render direto em browser ou imagem Markdown. Links são bearer URLs públicas protegidas por token de alta entropia, TTL, limite opcional de downloads e revogação explícita.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Lista URLs de download de arquivos locais geradas.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Revoga URL de download de arquivo local gerada.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Gateway MCP dinâmico

### `mcp_manage`

Registra, lista, obtém, habilita, desabilita, refresh, remove ou atualiza environment/headers isolados de servidores MCP dinâmicos. Use transport `stdio` com command/args/cwd ou `streamable_http` com url. Valores secret env/header são persistidos privadamente e nunca retornados.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `transport` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `args` | `array[string] \| null` | `null` |  |
| `cwd` | `string \| null` | `null` |  |
| `url` | `string \| null` | `null` |  |
| `env` | `object \| null` | `null` |  |
| `headers` | `object \| null` | `null` |  |
| `enabled` | `boolean` | `true` |  |
| `overwrite` | `boolean` | `false` |  |
| `refresh` | `boolean` | `true` |  |
| `key` | `string \| null` | `null` |  |
| `value` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Pesquisa summaries leves cacheados de tools de servidores MCP dinâmicos habilitados. Tools dinâmicas ficam fora de `tools/list` deste server; use o nome `<server>:<tool>` retornado com `mcp_tool_inspect` antes de chamar.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

Retorna schema completo cacheado de uma tool MCP dinâmica chamada `<server>:<tool>`. Faça refresh do server com `mcp_manage` se o cache estiver stale.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Chama uma tool MCP dinâmica cacheada chamada `<server>:<tool>`. Descubra com `mcp_tool_search` e inspecione schema com `mcp_tool_inspect` primeiro. Conexões MCP externas são abertas apenas durante esta chamada.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Inicia, lista, fecha ou limpa sessões browser persistentes de alto nível local ou remotamente. `start` pode abrir URL, reutilizar `profile_id` persistente ou carregar `storage_state_path`; `close` pode salvar storage state.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `browser` | `string` | `"chromium"` |  |
| `headless` | `boolean` | `true` |  |
| `width` | `integer` | `1440` |  |
| `height` | `integer` | `1000` |  |
| `url` | `string \| null` | `null` |  |
| `wait_until` | `string` | `"domcontentloaded"` |  |
| `profile_id` | `string \| null` | `null` |  |
| `storage_state_path` | `string \| null` | `null` |  |
| `save_storage_state_path` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `browser_snapshot`

Captura página browser persistente: title, URL, texto visível limitado, elementos interativos com refs curtas estáveis como `e1`, erros recentes page/network e path opcional de screenshot. Use as refs diretamente como targets de `browser_act` até ocorrer navegação ou novo snapshot.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `browser_act`

Executa ações estruturadas em sessão browser persistente. Suporta navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text e wait_for_url. `target` pode ser ref `browser_snapshot` como `e1` ou selector CSS. Use `browser_run_script` somente quando as ações de alto nível não bastarem.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

### `browser_run_script`

Executa script Python Playwright completo localmente ou em máquina remota.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.

## Automação de GUI de desktop

### `gui_list`

List visible desktop application windows and GUI backend capabilities locally or remotely.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_state`

Observe one desktop window before acting. Returns its accessibility elements plus an optional native MCP screenshot and a short-lived state_id. Prefer element_id actions; coordinate actions are relative to the observed window and are rejected if the window moved or resized.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `screenshot` | `boolean` | `true` |  |
| `include_elements` | `boolean` | `true` |  |
| `max_elements` | `integer` | `300` |  |
| `max_depth` | `integer` | `12` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_action`

Execute GUI actions against a fresh gui_state observation locally or remotely. The state_id is single-use. Prefer semantic element_id targeting; raw x/y coordinates are window-relative. Supported actions are click, double_click, right_click, move, scroll, drag, type, key, set_value, focus, and wait.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `state_id` | `string` | required |  |
| `actions` | `array[GuiAction]` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

## Administração de remote workers

### `remote_manage`

Gerencia remote workers com action=invite, list, revoke ou rename. invite aceita name/workdir/ttl_s; revoke exige machine; rename exige machine e new_name.

| Parâmetro | Tipo | Obrigatório/default | Descrição |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session desta chamada de tool. Enquanto trabalha na tarefa, passe o session_id retornado por session_manage. Use null somente quando não houver Logical Session ativa. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Quando `machine` é fornecido, a chamada também exige `remote:use` e é executada pelo protocolo de remote worker.
