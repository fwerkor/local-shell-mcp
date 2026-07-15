# REST API

Questa pagina descrive lo scenario “REST API” e mantiene la struttura Runtime/Client comune del sito.

## Panoramica

Runtime definisce come viene eseguito il processo server e quale workspace controlla. Client definisce come si collega ChatGPT o un altro client MCP. Docker, l’estensione VS Code, i binari autonomi, le installazioni Python/pipx/sorgente e stdio sono opzioni Runtime; il connettore ChatGPT, il client MCP HTTP generico e il client MCP stdio sono connessioni Client.

## Quando usarlo

- Usa questa pagina quando il percorso Runtime o Client scelto corrisponde al titolo.
- Mantieni coerenti radice del workspace, base URL pubblica, MCP endpoint, modalità di autenticazione e strumenti disponibili sull’host.
- Per ChatGPT web/app, esponi un MCP endpoint HTTPS che termini con `/mcp`.
- Per client MCP locali, usa HTTP localhost o `local-shell-mcp --mode stdio` in base al supporto del client.

## Passaggi

1. Scegli prima la pagina di installazione del Runtime.
2. Avvia il Runtime e verifica `/healthz` quando usi la modalità HTTP.
3. Poi scegli la pagina di connessione Client.
4. Registra il MCP endpoint o il comando stdio nel Client.
5. Chiama `environment_info` per verificare workspace e impostazioni effettive.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Verifica

- `environment_info` conferma impostazioni Runtime e workspace.
- `tree_view` conferma i file visibili.
- `run_shell_tool` conferma l’ambiente dei comandi.

## Note

Preferisci passaggi piccoli e verificabili: ispezionare, modificare, controllare il diff, testare, scansionare e fare commit. Anche le attività grandi dovrebbero essere divise in chiamate di strumenti auditabili.
