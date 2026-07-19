# Questions fréquentes

Cette page regroupe des problèmes récurrents de Client et de proxy inverse qui peuvent ressembler à des pannes LSM alors que le serveur fonctionne correctement.

## Pourquoi certains outils ChatGPT sont-ils indisponibles après une mise à niveau de LSM ?

### Symptômes

- Les nouveaux outils n’apparaissent pas dans ChatGPT.
- ChatGPT tente encore d’appeler un outil supprimé, renommé ou fusionné.
- L’outil existe, mais l’appel échoue parce que ChatGPT envoie un ancien schéma d’entrée.
- Redémarrer LSM ou ouvrir une nouvelle conversation ne résout pas le problème.

### Cause

ChatGPT peut conserver un instantané figé des outils et schémas d’entrée disponibles lors de l’analyse, de l’approbation ou de la publication d’une MCP App. Lorsqu’une version de LSM modifie `tools/list`, cet instantané n’est pas garanti d’être actualisé automatiquement. Il ne s’agit pas d’un cache de courte durée avec une expiration documentée.

### Solution

=== "Mode développeur ou connexion personnelle"

    1. Ouvrez **ChatGPT Settings → Apps**.
    2. Ouvrez l’App LSM et utilisez **Refresh** pour analyser à nouveau les outils.
    3. Si Refresh n’est pas disponible, supprimez l’ancienne App et ajoutez de nouveau le même endpoint MCP.
    4. Démarrez une nouvelle conversation après validation de la liste mise à jour.

=== "App publiée dans ChatGPT Business"

    Une App personnalisée publiée ne peut actuellement pas mettre à jour sur place ses outils ou métadonnées. Un administrateur doit créer une nouvelle App, analyser l’endpoint LSM actuel, publier le remplacement et retirer l’ancienne App.

=== "ChatGPT Enterprise ou Edu"

    Un administrateur peut ouvrir **Workspace Settings → Apps → LSM App → … → Action control → Refresh**, examiner les différences et activer les nouvelles actions si nécessaire.

Voir l’[issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) et la [documentation OpenAI sur les MCP Apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## Pourquoi WebUI se reconnecte-t-elle sans cesse derrière Nginx ?

### Symptômes

- La page WebUI et la connexion OAuth se chargent normalement.
- La TUI n’apparaît jamais.
- L’état alterne entre `Connecting`, `Connection error` et `Reconnecting`.
- Une connexion directe au port `8765` fonctionne.

### Cause

L’interface du navigateur affiche la TUI native via un PTY WebSocket. L’endpoint par défaut est `/ui/ws` ; avec un `ui_path` personnalisé, il devient `${ui_path}/ws`. Un `proxy_pass` Nginx normal ne transmet pas automatiquement les en-têtes hop-by-hop nécessaires à la mise à niveau WebSocket.

### Solution

Activez HTTP/1.1 et transmettez les en-têtes `Upgrade` et `Connection` :

```nginx
# Placez map dans le bloc http.
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

Validez puis rechargez Nginx :

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Dans Nginx Proxy Manager, activez **Websockets Support** pour le Proxy Host. Si les reconnexions continuent, ajoutez les en-têtes équivalents dans Advanced.

### Vérification

Ouvrez les outils de développement, rechargez WebUI et inspectez la requête `/ui/ws`. Une connexion correcte renvoie :

```text
101 Switching Protocols
```

Voir l’[issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
