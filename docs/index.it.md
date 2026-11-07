<!-- i18n-source-sha256: 276e9356b895a85759d31467512bdc530c9baa216a368df4ef1bccce39530d0e -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">Spazio di lavoro AI self-hosted · Piano di controllo MCP</span>

# local-shell-mcp

Chat, progetti, file, terminali, macchine remote e strumenti di intelligenza artificiale in un'unica interfaccia self-hosted. Connetti client MCP esterni quando ne hai bisogno.

<div class="hero-actions" markdown>
[Inizia](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Riferimento strumenti](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Ambiente di coding reale
Esegui test, ispeziona repository, applica patch ai file, usa Git e conserva un audit trail da un unico MCP endpoint.
</div>

<div class="feature-card" markdown>
### Spazio di lavoro Web unificato
Utilizza la chat integrata e la cronologia dei progetti insieme a file, terminali, desktop, sessioni, telecomandi e audit del controller. I client MCP esterni rimangono facoltativi.
</div>

<div class="feature-card" markdown>
### Controllo macchine remote
Collega macchine dietro NAT, firewall o HPC tramite connessioni worker in uscita senza aprire porte SSH.
</div>
</div>

## Cosa offre

`local-shell-mcp` fornisce uno spazio di lavoro AI self-hosted unificato e un server MCP per client esterni. Fornisce shell, shell persistente, filesystem, ricerca, patch, Git, Playwright, audit, sessioni logiche durevoli con piani obiettivo opzionali, collegamento file tokenizzato e strumenti per lavoratori remoti tramite endpoint MCP autenticati.

Usalo quando l’IA deve ispezionare un repository, eseguire test, modificare file, usare Git, raccogliere browser evidence, produrre downloadable artifacts o controllare una macchina remota che può soltanto collegarsi in uscita al control server.

## Architettura

```text
Livello runtime: Docker / VS Code extension / binary / Python / stdio
Livello esposizione: localhost / HTTPS proxy / tunnel / stdio pipe
Livello client: WebUI unificato/Gemini/ChatGPT/client MCP generico
Workspace controllato: /workspace or configured workspace root
Remote worker opzionali: outbound machine connections
```

Il confine di isolamento previsto è il container o la VM che esegue il servizio.

## Inizia per scenario

| Scenario | Inizia qui | Perché |
|---|---|---|
| Area di lavoro del browser principale | [Unified web workspace](getting-started/web-workspace.md) | Chat, progetti e pagine di controllo LSM con login condiviso |
| Distribuzione del primo controller | [Quickstart](getting-started/quickstart.md) | Deploy consigliato dai sorgenti, OAuth e prima sessione browser. |
| Scegliere il livello runtime | [Runtime choices](guides/deployment.md) | Spiega Docker, VS Code, binary, Python e stdio come opzioni runtime separate |
| Collegare Gemini Spark | [Gemini Custom Apps](getting-started/gemini-spark.md) | Idoneità, URL MCP HTTPS, OAuth e test |
| Aggiungere ChatGPT come client | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, primo prompt sicuro e tool discovery |
| Aggiungere LSM a DeepSeek Harness | [Plugin DeepSeek Harness](clients/deepseek-harness.md) | Installare questo repository come bundle DSH mantenendo l’intera superficie LSM e remote workers |
| Eseguire da VS Code | [VS Code extension runtime](installation/vscode-extension.md) | Runtime avviato dall’editor e note sulla sicurezza host |
| Imparare a usare il toolset | [Usage patterns](guides/usage-patterns.md) | Template di prompt e guida alla scelta degli strumenti |
| Capire ogni tool | [Tools reference](reference/tools.md) | Purpose, inputs, returns, combinations e notes per ogni tool |
| Collegare HPC, NPU/GPU o server node | [Remote workers](guides/remote-workers.md) | Outbound worker join flow e remote tool usage |
| Condividere file generati | [File links](guides/file-links.md) | URL download tokenizzati con TTL e revoca |
| Rafforzare il deployment | [Security](security.md) | Isolamento, OAuth, workspace scope e audit logs |

## Principali famiglie di tool

| Famiglia | Esempi | Uso |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Build, test, script e processi lunghi |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Ispezione repository ed edit precisi |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Workflow source-control facilmente revisionabili |
| Sessions e goal | `session_manage`, `plan_manage` | Handoff durevole dei task, progress report e Goal mode opzionale |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Interazione persistente, UI check, screenshot, docs renderizzati e testo pagina |
| File links | `link_create`, `link_revoke` | Scaricare artefatti generati dalla chat |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | Macchine dietro NAT, firewall o flussi di login cluster |

## Workflow tipici

### Codifica nell'area di lavoro web

1. Avviare un controller LSM e il [unified web workspace](getting-started/web-workspace.md) opzionale.
2. Apri `/ui` e accedi utilizzando l'identità LSM.
3. Configura un endpoint del modello e apri una nuova conversazione.
4. Chiedi al modello di ispezionare il repository ed eseguire prima i controlli di sola lettura.
5. Poi consenti patch ai file, test, review diff, commit e push quando approvati.
6. Controlla audit log quando il task coinvolge file link o sistemi remoti.

### Host HPC o acceleratore remoto

1. Crea un remote worker invite monouso.
2. Incolla il command generato sul remote host.
3. Usa tool normali con `machine`; Git via `run_shell` e transfer via `remote_transfer`.
4. Revoca il worker dopo il task.

### Generazione artefatti

1. Fai generare all’IA un file sotto `/workspace`.
2. Crea un tokenized file link con TTL/download limits.
3. Condividi il link in chat.
4. Revocalo al termine.

## Lingua

Questo site è costruito con il plugin i18n nativo di MkDocs. Usa il language selector nell’header per passare tra English e pagine tradotte. Le pagine senza traduzione fanno fallback a English.
