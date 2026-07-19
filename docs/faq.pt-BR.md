# Perguntas frequentes

Esta página reúne problemas recorrentes de Client e proxy reverso que podem parecer falhas do LSM mesmo quando o servidor está saudável.

## Por que algumas ferramentas ficam indisponíveis no ChatGPT após atualizar o LSM?

### Sintomas

- Ferramentas novas não aparecem no ChatGPT.
- O ChatGPT ainda tenta chamar uma ferramenta removida, renomeada ou unificada.
- A ferramenta existe, mas a chamada falha porque o ChatGPT envia um esquema de entrada antigo.
- Reiniciar o LSM ou abrir uma nova conversa não resolve.

### Causa

O ChatGPT pode manter um instantâneo congelado das ferramentas e dos esquemas de entrada disponíveis quando uma MCP App foi verificada, aprovada ou publicada. Quando uma versão do LSM altera `tools/list`, não há garantia de atualização automática desse instantâneo. Não é um cache de curta duração com prazo de expiração documentado.

### Solução

=== "Modo de desenvolvedor ou conexão pessoal"

    1. Abra **ChatGPT Settings → Apps**.
    2. Abra a App do LSM e use **Refresh** para verificar as ferramentas novamente.
    3. Se Refresh não estiver disponível, exclua a App antiga e adicione novamente o mesmo endpoint MCP.
    4. Inicie uma nova conversa depois de aceitar a lista atualizada.

=== "App publicada no ChatGPT Business"

    Uma App personalizada publicada não pode atualizar ferramentas ou metadados no local atualmente. Um administrador deve criar uma nova App, verificar o endpoint atual do LSM, publicar a substituta e desativar a App antiga.

=== "ChatGPT Enterprise ou Edu"

    Um administrador pode abrir **Workspace Settings → Apps → LSM App → … → Action control → Refresh**, revisar as diferenças e habilitar novas actions quando necessário.

Consulte a [issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) e a [documentação da OpenAI sobre MCP Apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## Por que a WebUI continua reconectando atrás do Nginx?

### Sintomas

- A página WebUI e o login OAuth carregam normalmente.
- A TUI nunca aparece.
- O estado alterna entre `Connecting`, `Connection error` e `Reconnecting`.
- O acesso direto à porta `8765` funciona.

### Causa

A interface do navegador renderiza a TUI nativa por meio de um PTY WebSocket. O endpoint padrão é `/ui/ws`; com um `ui_path` personalizado, ele é `${ui_path}/ws`. Um `proxy_pass` comum do Nginx não encaminha automaticamente os cabeçalhos hop-by-hop necessários para o upgrade de WebSocket.

### Solução

Ative HTTP/1.1 e encaminhe os cabeçalhos `Upgrade` e `Connection`:

```nginx
# Coloque map no bloco http.
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

Valide e recarregue o Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

No Nginx Proxy Manager, ative **Websockets Support** no Proxy Host. Se a reconexão continuar, adicione os cabeçalhos equivalentes em Advanced.

### Verificação

Abra as ferramentas de desenvolvedor, recarregue a WebUI e inspecione a solicitação `/ui/ws`. Uma conexão funcional retorna:

```text
101 Switching Protocols
```

Consulte a [issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
