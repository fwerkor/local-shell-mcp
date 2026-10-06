<!-- i18n-source-sha256: bfd205813bd40569d489f7e57417eef5098af2388cdb852b1016deb74a2fc0f1 -->
# Padrões de uso e guia de prompting

`local-shell-mcp` expõe ferramentas poderosas. Bons resultados dependem de pedir ao modelo que primeiro inspecione, aja em passos pequenos, verifique e relate o que mudou.

## Loop operacional geral

Use este loop na maioria das tarefas de código:

1. Inspecionar: `environment_get`, `file_tree`, `file_grep`, `file_read` e `run_shell` para comandos como `git status`.
2. Planejar: pedir ao modelo que identifique os arquivos e tests mínimos envolvidos.
3. Editar: usar `file_edit`, `file_patch` ou comandos shell.
4. Verificar: executar tests/builds direcionados com `run_shell` ou shells persistentes.
5. Revisar: executar `git diff` via `run_shell`, depois `secret_scan` e `audit_tail` quando necessário.
6. Commit/exportar: usar comandos Git CLI explícitos via `run_shell` ou `link_create`.

## Escolha de ferramentas

| Tarefa | Preferir | Evitar |
|---|---|---|
| Comando one-shot curto | `run_shell` | Iniciar shell persistente para cada comando |
| Dev server, REPL ou watch task longo | `shell_start` + `shell_read` + `shell_send` | Bloquear `run_shell` até timeout |
| Análise estruturada ou geração de arquivo | `run_python` | Pipelines shell frágeis para JSON/texto complexo |
| Pequena edição exata | `file_edit` | Reescrever arquivos inteiros desnecessariamente |
| Uma ou várias substituições em um arquivo | `file_edit` with an `edits` array | Repetir edits obsoletos sem reler |
| Patch multi-arquivo | `file_patch` | Edits shell ad hoc |
| Encontrar arquivos | `file_tree`, `file_glob` | Listagens recursivas completas de repositories grandes |
| Encontrar código | `file_grep` | Ler muitos arquivos às cegas |
| Evidência de navegador | `browser_snapshot`, `browser_run_script` | Adivinhar por nomes de páginas/routes |
| Artefatos baixáveis | `link_create` | Colar grande conteúdo binário no chat |
| Trabalho em máquina remota | normal tools with `machine`, plus `remote_transfer` | Abrir SSH de entrada quando outbound worker é suficiente |

## Chamar ferramentas pela CLI

Para scripts de shell e CI, `lsm call <tool>` invoca a mesma superfície de ferramentas registradas pelo controller loopback em execução, preservando os remote workers e o estado do controller.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Use `--session s_...` para associar a chamada a uma Logical Session. Na configuração Docker Compose documentada, o controller e a CLI do host compartilham `LOCAL_SHELL_MCP_UI_LOCAL_TOKEN` pelo `.env` do repositório com permissões restritas; outros layouts com runtimes separados podem usar `--token-file <path>`. `--direct` ignora o controller e funciona somente localmente.

## Templates de prompt

### Orientação read-only do repository

```text
Use local-shell-mcp. Inspecione o layout do repository e git status. Não modifique arquivos. Resuma os componentes principais, comandos de test que conseguir inferir e riscos óbvios antes de fazer mudanças.
```

### Correção focada de bug

```text
Use local-shell-mcp para corrigir o bug. Primeiro reproduza ou localize com o menor comando relevante. Leia os arquivos antes de editar. Faça um patch mínimo, execute a verificação direcionada e depois mostre git diff e os tests exatos executados. Não faça commit até eu aprovar.
```

### Workflow de commit e push

```text
Use local-shell-mcp. Verifique git status e diff, execute os tests relevantes e secret_scan, crie um commit focado com mensagem concisa e depois faça push da branch atual. Não inclua caches, build artifacts ou formatting não relacionado.
```

### Processo longo

```text
Inicie o dev server em uma persistent shell session, leia o output até ficar ready e depois use browser tools para verificar a página. Mantenha o session id e encerre depois da verificação.
```

### Tarefa em remote worker

```text
Use o remote worker conectado chamado <machine>. Primeiro chame environment_get com machine=<machine> e depois file_list com a mesma machine. Trabalhe somente dentro do remote workdir configurado. Use run_shell para comandos curtos e shell_start ou job_start para trabalho longo.
```

## Trabalhando com repositories

Sequência recomendada para mudanças open-source:

1. Executar `git status --short --branch` via `run_shell`.
2. Fazer fetch e inspecionar branches com Git CLI explícito quando upstream state importar.
3. Usar `file_grep` e `file_read` antes de editar.
4. Fazer patch mínimo.
5. Executar tests direcionados primeiro e tests mais amplos quando prático.
6. Executar `secret_scan` antes de commit ou push.
7. Stage e commit explícitos com mensagem concisa.

Peça um commit por mudança lógica quando maintainers precisarem de histórico revisável.

## Trabalhando com artefatos gerados

Para PDFs, reports, screenshots, archives ou logs:

1. Gerar o arquivo dentro do workspace.
2. Verificar que o arquivo existe e tem o tamanho esperado.
3. Usar `link_create` com TTL curto e `max_downloads` opcional.
4. Revogar o link quando não for mais necessário.

Não crie links públicos para private keys, credential directories ou dados pessoais não relacionados.

## Trabalhando com máquinas remotas

Remote worker mode é útil quando uma máquina pode fazer requests HTTPS de saída mas não aceitar SSH de entrada.

Boas práticas:

- Criar ou renomear máquinas com `remote_manage(action="invite", ...)` ou `remote_manage(action="rename", ...)`.
- Chamar `environment_get(machine=...)` antes de agir.
- Usar `remote_transfer` para iniciar transfer jobs controller/worker ou worker/worker e gerenciá-los com tools `job_*` normais.
- Revogar workers após a tarefa com `remote_manage(action="revoke", ...)`.

## Anti-patterns

Evite estas instruções, a menos que o ambiente seja descartável e as consequências sejam entendidas:

- “Instale globalmente o que for necessário” em server iniciado no host.
- “Execute até funcionar” sem limites de tempo ou critérios de verificação.
- “Commit tudo” em repository com artefatos gerados.
- “Exponha todo o home directory” por conveniência.
- “Crie um file link para todo o workspace”.
- Executar deployment público com `LOCAL_SHELL_MCP_AUTH_MODE=none`.
