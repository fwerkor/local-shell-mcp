<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# Łączność sieciowa

HTTP MCP client znajdujące się poza maszyną potrzebują osiągalnego HTTPS origin. Ta strona dotyczy routingu sieciowego, a nie wyboru runtime.

client endpoint zwykle kończy się na `/mcp`:

```text
https://your-public-host.example.com/mcp
```

Ustawienie public base URL serwera zawiera wyłącznie origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Nie dodawaj `/mcp` do tego base URL.

## Opcje łączności

**Zalecane:** Do dostępu publicznego użyj serwera z publicznym adresem lub przekierowania przez serwer publiczny z odwrotnym proxy HTTPS.

**Niezalecane:** Przesyłanie danych od klienta przez Cloudflare Tunnel może być bardzo wolne, co utrudnia wysyłanie i transfer plików. Używaj tylko wtedy, gdy serwer publiczny lub przekierowanie nie są dostępne.


| Opcja | Kiedy używać |
|---|---|
| Caddy | Prosty automatyczny TLS |
| Nginx lub Nginx Proxy Manager | Istniejąca infrastruktura Nginx |
| Traefik | Istniejący routing container-native |
| Przekierowanie przez serwer publiczny | Do dostępu publicznego użyj serwera z publicznym adresem lub przekierowania przez serwer publiczny z odwrotnym proxy HTTPS. |
| Cloudflare Tunnel (niezalecane) | Przekierowanie przez serwer publiczny; Cloudflare Tunnel tylko awaryjnie |

## Ścieżki

Przekieruj cały origin do uruchomionego serwera. Ważne ścieżki obejmują:

| Ścieżka | Zastosowanie |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Kontrole stanu |
| `/.well-known/...` | Metadane client discovery |
| `/oauth/...` | Przepływ autoryzacji client |
| `/downloads/...` | Opcjonalne linki do wygenerowanych plików |
| `/join/...`, `/remote/...` | Opcjonalny przepływ remote-worker |

## Zachowanie proxy

Proxy powinno zachowywać ścieżki, przekazywać request body, obsługiwać długie response’y i unikać bardzo krótkich timeoutów.

## Kontrole

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Częste błędy

| Błąd | Naprawa |
|---|---|
| Użycie w ChatGPT `https://host` zamiast `https://host/mcp` | Dodaj `/mcp` tylko do client endpoint |
| Ustawienie `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | Ustaw tylko origin |
| Routing tylko `/mcp` | Routuj cały origin, aby działały także discovery i autoryzacja |
| Uruchamianie host runtime ze zbyt szerokim workspace | Użyj wąskiego workspace lub Docker |

## Sugerowane połączenia

| Runtime | Schemat sieci |
|---|---|
| Docker Compose na serwerze | Odwrotne proxy HTTPS |
| Docker Compose na komputerze domowym | Przekierowanie przez serwer publiczny; Cloudflare Tunnel tylko awaryjnie |
| VS Code extension na laptopie | Przekierowanie przez serwer publiczny |
| Binary na VM | Reverse proxy na VM lub brzegu sieci |
| Python/source dev server | Zwykle tylko localhost |
| Stdio mode | Brak ścieżki HTTP; użyj lokalnego MCP client |
