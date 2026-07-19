# Preguntas frecuentes

Esta página reúne problemas recurrentes de Client y proxy inverso que pueden parecer fallos de LSM aunque el servidor esté funcionando correctamente.

## ¿Por qué algunas herramientas no están disponibles en ChatGPT después de actualizar LSM?

### Síntomas

- Las herramientas nuevas no aparecen en ChatGPT.
- ChatGPT intenta llamar a una herramienta eliminada, renombrada o combinada.
- La herramienta existe, pero la llamada falla porque ChatGPT envía un esquema de entrada antiguo.
- Reiniciar LSM o abrir una conversación nueva no soluciona el problema.

### Causa

ChatGPT puede conservar una instantánea congelada de las herramientas y los esquemas de entrada disponibles cuando se analizó, aprobó o publicó una MCP App. Cuando una versión de LSM cambia `tools/list`, no se garantiza que esa instantánea se actualice automáticamente. No es una caché de corta duración con una caducidad documentada.

### Solución

=== "Modo de desarrollador o conexión personal"

    1. Abra **ChatGPT Settings → Apps**.
    2. Abra la App de LSM y use **Refresh** para volver a analizar las herramientas.
    3. Si Refresh no está disponible, elimine la App antigua y añada de nuevo el mismo endpoint MCP.
    4. Inicie una conversación nueva después de aceptar la lista actualizada.

=== "App publicada en ChatGPT Business"

    Actualmente, una App personalizada publicada no puede actualizar sus herramientas o metadatos en el mismo lugar. Un administrador debe crear otra App, analizar el endpoint actual de LSM, publicar el reemplazo y retirar la App anterior.

=== "ChatGPT Enterprise o Edu"

    Un administrador puede abrir **Workspace Settings → Apps → LSM App → … → Action control → Refresh**, revisar las diferencias y habilitar las acciones nuevas cuando sea necesario.

Consulte el [issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) y la [documentación de MCP Apps de OpenAI](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## ¿Por qué WebUI se reconecta continuamente detrás de Nginx?

### Síntomas

- La página WebUI y el inicio de sesión OAuth cargan correctamente.
- La TUI nunca aparece.
- El estado alterna entre `Connecting`, `Connection error` y `Reconnecting`.
- La conexión directa al puerto `8765` funciona.

### Causa

La interfaz del navegador renderiza la TUI nativa mediante un PTY WebSocket. El endpoint predeterminado es `/ui/ws`; con un `ui_path` personalizado es `${ui_path}/ws`. Un `proxy_pass` normal de Nginx no reenvía automáticamente los encabezados hop-by-hop necesarios para actualizar a WebSocket.

### Solución

Active HTTP/1.1 y reenvíe los encabezados `Upgrade` y `Connection`:

```nginx
# Coloque map en el bloque http.
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

Después, valide y recargue Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

En Nginx Proxy Manager, active **Websockets Support** en el Proxy Host. Si continúa la reconexión, añada los encabezados equivalentes en Advanced.

### Verificación

Abra las herramientas de desarrollo, recargue WebUI y revise la solicitud `/ui/ws`. Una conexión correcta devuelve:

```text
101 Switching Protocols
```

Consulte el [issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
