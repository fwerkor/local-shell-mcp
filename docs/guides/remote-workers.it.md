<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Worker remoti

I remote worker consentono a `local-shell-mcp` di controllare macchine che possono effettuare richieste HTTP(S) in uscita ma non accettare connessioni SSH in ingresso.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Workflow di base

1. Crea un invito con `remote_manage(action="invite", ...)`.
2. Esegui il comando generato sulla macchina remota.
3. Conferma la registrazione con `remote_manage(action="list")`.
4. Chiama gli strumenti normali con `machine="<worker-name>"`, per esempio `environment_get`, `run_shell`, `file_read` o `browser_run_script`.
5. Usa `remote_transfer` per avviare un trasferimento tracciato controller-to-worker, worker-to-controller o worker-to-worker di file o directory. Seguilo con `job_list` o `job_tail`; interrompi o riprova con `job_stop` o `job_retry`.
6. Rinomina o revoca worker con `remote_manage(action="rename", ...)` o `remote_manage(action="revoke", ...)`.

Solo l’amministrazione dei worker usa nomi `remote_*`. Le operazioni execution, shell, job, filesystem, patch e browser condividono lo stesso schema localmente e da remoto. Specificare una machine richiede anche l’OAuth scope `remote:use`.

## Worker persistenti

Il risultato dell’invito contiene comandi specifici della piattaforma:

- `persistent_command` installa e avvia un servizio utente su Linux o macOS.
- `powershell_persistent_command` installa e avvia una Windows user task da PowerShell.

Su Windows, `local-shell-mcp worker install-service` registra l’attività `local-shell-mcp-worker` per l’utente corrente. Parte subito, riparte quando quell’utente accede dopo un reboot, permette il funzionamento a batteria, ignora avvii duplicati e ritenta esecuzioni fallite. Non richiede privilegi amministrativi e non viene eseguita prima del login dell’utente.

Usa gli stessi lifecycle commands su ogni piattaforma:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

Il log del worker è memorizzato nel worker state directory come `worker.log`.

## Capacità

I worker supportano shell/persistent shell sessions, tracked jobs, operazioni filesystem, transfer internals, esecuzione Python, patches e Playwright dove sono installate le dipendenze. Git usa comandi standard tramite `run_shell(machine=...)`.

## Sicurezza e versionamento

Un worker collegato dà al MCP client controllo sul suo ambiente configurato. Usa invite TTL brevi, work directories o account dedicati, esamina gli audit logs e revoca i worker al termine. L’invito generato installa codice worker corrispondente alla versione del control server.

## Risoluzione dei problemi

Se un worker non compare, controlla accesso HTTPS in uscita, raggiungibilità del public base URL, scadenza dell’invito, ora di sistema e logs del control server.
