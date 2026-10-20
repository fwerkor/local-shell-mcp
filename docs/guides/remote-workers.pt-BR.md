<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Workers remotos

Remote workers permitem que `local-shell-mcp` controle máquinas que podem fazer requisições HTTP(S) de saída, mas não podem aceitar conexões SSH de entrada.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Fluxo básico

1. Crie um convite com `remote_manage(action="invite", ...)`.
2. Execute o comando gerado na máquina remota.
3. Confirme o registro com `remote_manage(action="list")`.
4. Chame ferramentas normais com `machine="<worker-name>"`, por exemplo `environment_get`, `run_shell`, `file_read` ou `browser_run_script`.
5. Use `remote_transfer` para iniciar uma transferência rastreada controller-to-worker, worker-to-controller ou worker-to-worker de arquivo ou diretório. Acompanhe com `job_list` ou `job_tail`; pare ou repita com `job_stop` ou `job_retry`.
6. Renomeie ou revogue workers com `remote_manage(action="rename", ...)` ou `remote_manage(action="revoke", ...)`.

Somente a administração de workers usa nomes `remote_*`. Operações de execution, shell, job, filesystem, patch e browser compartilham o mesmo schema local e remotamente. Informar uma machine exige adicionalmente o OAuth scope `remote:use`.

## Workers persistentes

O resultado do convite contém comandos específicos da plataforma:

- `persistent_command` instala e inicia um serviço de usuário no Linux ou macOS.
- `powershell_persistent_command` instala e inicia uma tarefa de usuário do Windows pelo PowerShell.

No Windows, `local-shell-mcp worker install-service` registra a tarefa `local-shell-mcp-worker` para o usuário atual. Ela inicia imediatamente, volta a iniciar quando esse usuário faz logon após um reboot, permite operação com bateria, ignora inicializações duplicadas e repete execuções que falharam. Não exige privilégios administrativos e não executa antes do usuário entrar.

Use os mesmos comandos de lifecycle em todas as plataformas:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

O log do worker fica no worker state directory como `worker.log`.

## Capacidades

Workers suportam shell/persistent shell sessions, tracked jobs, operações filesystem, transfer internals, execução Python, patches e Playwright onde as dependências estiverem instaladas. Git usa comandos padrão via `run_shell(machine=...)`.

## Segurança e versionamento

Um worker conectado dá ao MCP client controle sobre o ambiente configurado. Use invite TTLs curtos, work directories ou contas dedicadas, revise audit logs e revogue workers ao finalizar. O convite gerado instala código do worker correspondente à versão do control server.

## Solução de problemas

Se um worker não aparecer, verifique acesso HTTPS de saída, alcance do public base URL, expiração do convite, hora do sistema e logs do control server.
