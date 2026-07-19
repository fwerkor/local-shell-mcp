# Domande frequenti

Questa pagina raccoglie problemi ricorrenti di Client e reverse proxy che possono sembrare guasti di LSM anche quando il server funziona correttamente.

## Perché alcuni strumenti non sono disponibili in ChatGPT dopo l’aggiornamento di LSM?

### Sintomi

- I nuovi strumenti non compaiono in ChatGPT.
- ChatGPT tenta ancora di chiamare uno strumento rimosso, rinominato o unificato.
- Lo strumento esiste, ma la chiamata fallisce perché ChatGPT invia un vecchio schema di input.
- Riavviare LSM o aprire una nuova conversazione non risolve il problema.

### Causa

ChatGPT può conservare un’istantanea congelata degli strumenti e degli schemi di input disponibili quando una MCP App è stata analizzata, approvata o pubblicata. Se una versione di LSM modifica `tools/list`, l’aggiornamento automatico dell’istantanea non è garantito. Non è una cache breve con una scadenza documentata.

### Soluzione

=== "Modalità sviluppatore o connessione personale"

    1. Aprire **ChatGPT Settings → Apps**.
    2. Aprire la LSM App e usare **Refresh** per analizzare nuovamente gli strumenti.
    3. Se Refresh non è disponibile, eliminare la vecchia App e aggiungere di nuovo lo stesso endpoint MCP.
    4. Avviare una nuova conversazione dopo aver accettato l’elenco aggiornato.

=== "App pubblicata in ChatGPT Business"

    Al momento una App personalizzata pubblicata non può aggiornare strumenti o metadati sul posto. Un amministratore deve creare una nuova App, analizzare l’endpoint LSM corrente, pubblicare la sostituta e ritirare la vecchia App.

=== "ChatGPT Enterprise o Edu"

    Un amministratore può aprire **Workspace Settings → Apps → LSM App → … → Action control → Refresh**, esaminare le differenze e abilitare le nuove actions quando necessario.

Vedere l’[issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) e la [documentazione OpenAI sulle MCP Apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## Perché la WebUI continua a riconnettersi dietro Nginx?

### Sintomi

- La pagina WebUI e l’accesso OAuth vengono caricati normalmente.
- La TUI non appare.
- Lo stato passa ripetutamente tra `Connecting`, `Connection error` e `Reconnecting`.
- Il collegamento diretto alla porta `8765` funziona.

### Causa

L’interfaccia del browser visualizza la TUI nativa tramite un PTY WebSocket. L’endpoint predefinito è `/ui/ws`; con un `ui_path` personalizzato è `${ui_path}/ws`. Un normale `proxy_pass` Nginx non inoltra automaticamente gli header hop-by-hop necessari per l’upgrade WebSocket.

### Soluzione

Abilitare HTTP/1.1 e inoltrare gli header `Upgrade` e `Connection`:

```nginx
# Inserire map nel blocco http.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

Verificare e ricaricare Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

In Nginx Proxy Manager, abilitare **Websockets Support** sul Proxy Host. Se le riconnessioni continuano, aggiungere gli header equivalenti in Advanced.

### Verifica

Aprire gli strumenti di sviluppo, ricaricare WebUI e controllare la richiesta `/ui/ws`. Una connessione funzionante restituisce:

```text
101 Switching Protocols
```

Vedere l’[issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
