<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# Connettività di rete

Gli MCP client HTTP esterni alla macchina richiedono un HTTPS origin raggiungibile. Questa pagina riguarda il routing di rete, non la scelta del runtime.

Il client endpoint termina normalmente con `/mcp`:

```text
https://your-public-host.example.com/mcp
```

L’impostazione public base URL del server contiene solo l’origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Non includere `/mcp` in questa base URL.

## Opzioni di connettività

**Consigliato:** Per l'accesso pubblico, distribuisci su un server pubblico oppure inoltra il traffico tramite un server pubblico con reverse proxy HTTPS.

**Sconsigliato:** La velocità di upload lato client di Cloudflare Tunnel può essere molto bassa, rendendo difficili caricamenti e trasferimenti di file. Usalo solo se non sono possibili un server pubblico o un inoltro tramite esso.


| Opzione | Quando usarla |
|---|---|
| Caddy | TLS automatico semplice |
| Nginx o Nginx Proxy Manager | Infrastruttura Nginx esistente |
| Traefik | Routing container-native esistente |
| Inoltro tramite server pubblico | Per l'accesso pubblico, distribuisci su un server pubblico oppure inoltra il traffico tramite un server pubblico con reverse proxy HTTPS. |
| Cloudflare Tunnel (sconsigliato) | Inoltro tramite server pubblico; Cloudflare Tunnel solo come ripiego |

## Percorsi

Inoltra l’intero origin al server in esecuzione. I percorsi importanti includono:

| Percorso | Scopo |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Controlli di stato |
| `/.well-known/...` | Metadati di discovery del client |
| `/oauth/...` | Flusso di autorizzazione del client |
| `/downloads/...` | Link opzionali ai file generati |
| `/join/...`, `/remote/...` | Flusso remote-worker opzionale |

## Comportamento del proxy

Il proxy deve preservare i percorsi, inoltrare i request bodies, supportare responses lunghe ed evitare timeout troppo brevi.

## Controlli

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Errori comuni

| Errore | Correzione |
|---|---|
| Usare `https://host` in ChatGPT invece di `https://host/mcp` | Aggiungere `/mcp` solo al client endpoint |
| Impostare `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | Impostare solo l’origin |
| Inoltrare solo `/mcp` | Inoltrare tutto l’origin in modo che funzionino anche discovery e autorizzazione |
| Eseguire un host runtime con workspace troppo ampio | Usare un workspace ristretto o Docker |

## Abbinamento consigliato

| Runtime | Schema di rete |
|---|---|
| Docker Compose su server | Reverse proxy HTTPS |
| Docker Compose su macchina domestica | Inoltro tramite server pubblico; Cloudflare Tunnel solo come ripiego |
| VS Code extension su laptop | Inoltro tramite server pubblico |
| Binary su VM | Reverse proxy sulla VM o al bordo della rete |
| Server di sviluppo Python/source | Di solito solo localhost |
| Stdio mode | Nessun percorso HTTP; usare un MCP client locale |
