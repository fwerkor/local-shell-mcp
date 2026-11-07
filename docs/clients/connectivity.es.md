<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# Conectividad de red

Los MCP client HTTP que estén fuera de la máquina necesitan un HTTPS origin accesible. Esta página trata del enrutamiento de red, no de qué runtime elegir.

El client endpoint normalmente termina en `/mcp`:

```text
https://your-public-host.example.com/mcp
```

La configuración de public base URL del servidor contiene solo el origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

No incluya `/mcp` en esa base URL.

## Opciones de conectividad

**Recomendado:** Para el acceso público, usa un servidor público o reenvía el tráfico a través de uno con un proxy inverso HTTPS.

**No recomendado:** Las subidas del cliente por Cloudflare Tunnel pueden ser muy lentas, lo que dificulta el uso de las funciones de carga y transferencia de archivos. Úsalo solo si no es viable desplegar o reenviar mediante un servidor público.


| Opción | Cuándo usarla |
|---|---|
| Caddy | TLS automático sencillo |
| Nginx o Nginx Proxy Manager | Infraestructura Nginx existente |
| Traefik | Enrutamiento container-native existente |
| Reenvío mediante servidor público | Para el acceso público, usa un servidor público o reenvía el tráfico a través de uno con un proxy inverso HTTPS. |
| Cloudflare Tunnel (no recomendado) | Reenviar mediante servidor público; Cloudflare Tunnel solo como último recurso |

## Rutas

Reenvíe todo el origin al servidor en ejecución. Entre las rutas importantes se incluyen:

| Ruta | Propósito |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Comprobaciones de salud |
| `/.well-known/...` | Metadatos de descubrimiento del client |
| `/oauth/...` | Flujo de autorización del client |
| `/downloads/...` | Enlaces opcionales a archivos generados |
| `/join/...`, `/remote/...` | Flujo opcional de remote-worker |

## Comportamiento del proxy

El proxy debe conservar las rutas, reenviar los request bodies, admitir responses largas y evitar timeouts demasiado cortos.

## Comprobaciones

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Errores frecuentes

| Error | Solución |
|---|---|
| Usar `https://host` en ChatGPT en vez de `https://host/mcp` | Añadir `/mcp` solo al client endpoint |
| Definir `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | Definir solo el origin |
| Enrutar únicamente `/mcp` | Enrutar todo el origin para que también funcionen el descubrimiento y la autorización |
| Ejecutar un host runtime con un workspace demasiado amplio | Usar un workspace limitado o Docker |

## Combinaciones sugeridas

| Runtime | Patrón de red |
|---|---|
| Docker Compose en un servidor | Proxy inverso HTTPS |
| Docker Compose en una máquina doméstica | Reenviar mediante servidor público; Cloudflare Tunnel solo como último recurso |
| VS Code extension en un portátil | Reenvío mediante servidor público |
| Binary en una VM | Reverse proxy en la VM o en el borde de red |
| Servidor de desarrollo Python/source | Normalmente solo localhost |
| Stdio mode | Sin ruta HTTP; usar un MCP client local |
