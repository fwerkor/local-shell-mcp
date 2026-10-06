<!-- i18n-source-sha256: 382c9edbbba8fa4fb3aab11dcc4127ba80bff8c7104bdedffdf66b9bbcdb744a -->
# Modelli di utilizzo e guida ai prompt

`local-shell-mcp` espone strumenti potenti. I risultati migliori arrivano chiedendo al modello di ispezionare prima, agire in piccoli passi, verificare e riportare cosa è cambiato.

## Ciclo operativo generale

Usa questo ciclo per la maggior parte dei task di coding:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read` e `run_shell` per comandi come `git status`.
2. Plan: chiedi al modello di individuare il minimo insieme di file e test coinvolti.
3. Edit: usa `file_edit`, `file_patch` o comandi shell.
4. Verify: esegui test/build mirati con `run_shell` o shell persistenti.
5. Review: esegui `git diff` tramite `run_shell`, poi `secret_scan` e `audit_tail` quando servono.
6. Commit/export: usa comandi Git CLI espliciti tramite `run_shell` oppure `link_create`.

## Scelta degli strumenti

| Task | Preferire | Evitare |
|---|---|---|
| Comando one-shot rapido | `run_shell` | Avviare una shell persistente per ogni comando |
| Dev server, REPL o watch task lungo | `shell_start` + `shell_read` + `shell_send` | Bloccare `run_shell` fino al timeout |
| Analisi strutturata o generazione di file | `run_python` | Pipeline shell fragili per JSON/testo complesso |
| Piccola modifica esatta | `file_edit` | Riscrivere interi file senza necessità |
| Una o più sostituzioni in un file | `file_edit` with an `edits` array | Ripetere edit stale senza rileggere |
| Patch multi-file | `file_patch` | Edit shell ad hoc |
| Trovare file | `file_tree`, `file_glob` | Listing ricorsivi completi di repository grandi |
| Trovare codice | `file_grep` | Leggere molti file alla cieca |
| Evidenza browser | `browser_snapshot`, `browser_run_script` | Indovinare da nomi di pagina o route |
| Artefatti scaricabili | `link_create` | Incollare grandi contenuti binari in chat |
| Lavoro su macchina remota | normal tools with `machine`, plus `remote_transfer` | Aprire SSH inbound quando basta outbound worker |

## Chiamare gli strumenti dalla CLI

Per script shell e CI, `lsm call <tool>` richiama la stessa superficie di strumenti registrati tramite il controller loopback in esecuzione, preservando i remote worker e lo stato del controller.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Usa `--session s_...` per associare la chiamata a una Logical Session. Nella configurazione Docker Compose documentata, il `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN` grezzo rimane solo nel `.env` di proprietà dell’host e con permessi limitati, mentre Compose passa al controller soltanto il verificatore SHA-256; altri layout con runtime separati possono usare `--token-file <path>`. `--direct` bypassa il controller, applica nel processo le impostazioni runtime del `.env` corrente, non inietta il token CLI dell’host nell’ambiente dello strumento ed è disponibile solo localmente. Il token Human UI non viene mai accettato da `/mcp`; nei runtime separati il controller deve configurare il `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256` corrispondente.

## Template di prompt

### Orientamento read-only del repository

```text
Usa local-shell-mcp. Ispeziona il layout del repository e git status. Non modificare file. Riassumi i componenti principali, i comandi di test che puoi dedurre e i rischi evidenti prima di fare cambiamenti.
```

### Correzione focalizzata di bug

```text
Usa local-shell-mcp per correggere il bug. Prima riproducilo o localizzalo con il comando rilevante più piccolo. Leggi i file prima di modificarli. Crea una patch minima, esegui la verifica mirata, poi mostra git diff e i test esatti eseguiti. Non fare commit finché non approvo.
```

### Workflow commit e push

```text
Usa local-shell-mcp. Controlla git status e diff, esegui i test rilevanti e secret_scan, crea un solo commit focalizzato con messaggio conciso, poi fai push del branch corrente. Non includere cache, artefatti di build o formatting non correlato.
```

### Processo di lunga durata

```text
Avvia il dev server in una persistent shell session, leggi l’output finché non è ready, poi usa browser tools per verificare la pagina. Mantieni il session id e termina la sessione dopo la verifica.
```

### Task su remote worker

```text
Usa il remote worker connesso chiamato <machine>. Prima chiama environment_get con machine=<machine>, poi file_list con la stessa machine. Lavora solo nel remote workdir configurato. Usa run_shell per comandi brevi e shell_start o job_start per lavori lunghi.
```

## Lavorare con i repository

Sequenza consigliata per modifiche open-source:

1. Esegui `git status --short --branch` tramite `run_shell`.
2. Fai fetch e ispeziona i branch con comandi Git CLI espliciti quando conta lo stato upstream.
3. Usa `file_grep` e `file_read` prima di modificare.
4. Crea una patch minima.
5. Esegui prima i test mirati e poi test più ampi quando pratico.
6. Esegui `secret_scan` prima di commit o push.
7. Fai stage e commit in modo esplicito con un messaggio conciso.

Chiedi un commit per ogni modifica logica quando i maintainer hanno bisogno di una cronologia facile da revisionare.

## Lavorare con artefatti generati

Per PDF, report, screenshot, archivi o log:

1. Genera il file nel workspace.
2. Verifica che esista e abbia la dimensione attesa.
3. Usa `link_create` con TTL breve e `max_downloads` opzionale.
4. Revoca il link quando non serve più.

Non creare link pubblici per chiavi private, directory di credenziali o dati personali non correlati.

## Lavorare con macchine remote

Remote worker mode è utile quando una macchina può fare richieste HTTPS in uscita ma non accettare SSH in ingresso.

Buone pratiche:

- Crea o rinomina macchine con `remote_manage(action="invite", ...)` o `remote_manage(action="rename", ...)`.
- Chiama `environment_get(machine=...)` prima di agire.
- Usa `remote_transfer` per avviare transfer job controller/worker o worker/worker, poi gestiscili con i normali strumenti `job_*`.
- Revoca i worker dopo il task con `remote_manage(action="revoke", ...)`.

## Anti-pattern

Evita queste istruzioni salvo che l’ambiente sia disposable e le conseguenze siano comprese:

- “Installa globalmente tutto ciò che serve” su un server avviato sull’host.
- “Esegui finché funziona” senza limiti temporali o criteri di verifica.
- “Fai commit di tutto” in un repository con artefatti generati.
- “Esponi tutta la home directory” per comodità.
- “Crea un file link per l’intero workspace”.
- Eseguire deployment pubblici con `LOCAL_SHELL_MCP_AUTH_MODE=none`.
