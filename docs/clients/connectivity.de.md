<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# Netzwerkverbindung

HTTP-MCP-client außerhalb der Maschine benötigen einen erreichbaren HTTPS-Origin. Diese Seite behandelt das Netzwerk-Routing, nicht die Wahl des Runtime.

Der client endpoint endet normalerweise auf `/mcp`:

```text
https://your-public-host.example.com/mcp
```

Die public base URL des Servers enthält nur den Origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Nehmen Sie `/mcp` nicht in diese base URL auf.

## Verbindungsoptionen

**Empfohlen:** Für öffentlichen Zugriff einen öffentlichen Server oder eine Weiterleitung über einen öffentlichen Server mit HTTPS-Reverse-Proxy verwenden.

**Nicht empfohlen:** Bei Cloudflare Tunnel kann der clientseitige Upload sehr langsam sein, sodass Datei-Uploads und -Übertragungen kaum nutzbar sind. Nur verwenden, wenn direkte Bereitstellung oder Weiterleitung über einen öffentlichen Server nicht möglich ist.


| Option | Einsatz |
|---|---|
| Caddy | Einfaches automatisches TLS |
| Nginx oder Nginx Proxy Manager | Vorhandene Nginx-Infrastruktur |
| Traefik | Vorhandenes container-natives Routing |
| Weiterleitung über öffentlichen Server | Für öffentlichen Zugriff einen öffentlichen Server oder eine Weiterleitung über einen öffentlichen Server mit HTTPS-Reverse-Proxy verwenden. |
| Cloudflare Tunnel (nicht empfohlen) | Über öffentlichen Server weiterleiten; Cloudflare Tunnel nur als Notlösung |

## Pfade

Leiten Sie den gesamten Origin an den laufenden Server weiter. Wichtige Pfade sind:

| Pfad | Zweck |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health Checks |
| `/.well-known/...` | Metadaten zur client discovery |
| `/oauth/...` | Autorisierungsablauf des client |
| `/downloads/...` | Optionale Links zu generierten Dateien |
| `/join/...`, `/remote/...` | Optionaler remote-worker-Ablauf |

## Proxy-Verhalten

Der Proxy sollte Pfade unverändert lassen, request bodies weiterleiten, lange responses unterstützen und sehr kurze Timeouts vermeiden.

## Prüfungen

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Häufige Fehler

| Fehler | Korrektur |
|---|---|
| In ChatGPT `https://host` statt `https://host/mcp` verwenden | `/mcp` nur am client endpoint ergänzen |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` setzen | Nur den Origin setzen |
| Nur `/mcp` routen | Den gesamten Origin routen, damit Discovery und Autorisierung ebenfalls funktionieren |
| Einen host runtime mit zu breitem Workspace ausführen | Einen engen Workspace oder Docker verwenden |

## Empfohlene Kombinationen

| Runtime | Netzwerkmuster |
|---|---|
| Docker Compose auf einem Server | HTTPS-Reverse-Proxy |
| Docker Compose auf einem Heimrechner | Über öffentlichen Server weiterleiten; Cloudflare Tunnel nur als Notlösung |
| VS Code extension auf einem Laptop | Weiterleitung über öffentlichen Server |
| Binary auf einer VM | Reverse Proxy auf der VM oder am Netzwerkrand |
| Python/source-Entwicklungsserver | Normalerweise nur localhost |
| Stdio mode | Kein HTTP-Netzpfad; lokalen MCP client verwenden |
