<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# Ağ bağlantısı

Makine dışındaki HTTP MCP client’ların erişilebilir bir HTTPS origin’e ihtiyacı vardır. Bu sayfa ağ yönlendirmesini açıklar; hangi runtime’ın seçileceğini değil.

client endpoint normalde `/mcp` ile biter:

```text
https://your-public-host.example.com/mcp
```

Sunucunun public base URL ayarı yalnızca origin’i içerir:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Bu base URL’ye `/mcp` eklemeyin.

## Bağlantı seçenekleri

**Önerilir:** Genel erişim için herkese açık bir sunucuya dağıtın veya trafiği HTTPS ters vekiliyle herkese açık bir sunucu üzerinden iletin.

**Önerilmez:** Cloudflare Tunnel üzerinden istemci tarafındaki yükleme hızı çok düşük olabilir; bu da dosya yükleme ve aktarımı işlevlerini kullanmayı zorlaştırır. Yalnızca genel sunucu veya yönlendirme mümkün değilse kullanın.


| Seçenek | Ne zaman kullanılır |
|---|---|
| Caddy | Basit otomatik TLS |
| Nginx veya Nginx Proxy Manager | Mevcut Nginx altyapısı |
| Traefik | Mevcut container-native yönlendirme |
| Genel sunucu üzerinden yönlendirme | Genel erişim için herkese açık bir sunucuya dağıtın veya trafiği HTTPS ters vekiliyle herkese açık bir sunucu üzerinden iletin. |
| Cloudflare Tunnel (önerilmez) | Genel sunucu üzerinden yönlendirin; Cloudflare Tunnel son çare olsun |

## Yollar

Tüm origin’i çalışan sunucuya iletin. Önemli yollar şunlardır:

| Yol | Amaç |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Sağlık kontrolleri |
| `/.well-known/...` | Client discovery meta verileri |
| `/oauth/...` | Client yetkilendirme akışı |
| `/downloads/...` | İsteğe bağlı oluşturulan dosya bağlantıları |
| `/join/...`, `/remote/...` | İsteğe bağlı remote-worker akışı |

## Proxy davranışı

Proxy yolları korumalı, request body’leri iletmeli, uzun response’ları desteklemeli ve çok kısa timeout’lardan kaçınmalıdır.

## Kontroller

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Yaygın hatalar

| Hata | Düzeltme |
|---|---|
| ChatGPT’de `https://host/mcp` yerine `https://host` kullanmak | `/mcp` yalnızca client endpoint’e eklenir |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` ayarlamak | Yalnızca origin’i ayarlayın |
| Yalnızca `/mcp` yolunu yönlendirmek | Discovery ve yetkilendirme yolları da çalışsın diye tüm origin’i yönlendirin |
| Host runtime’ı çok geniş bir workspace ile çalıştırmak | Dar workspace veya Docker kullanın |

## Önerilen eşleşmeler

| Runtime | Ağ deseni |
|---|---|
| Sunucuda Docker Compose | HTTPS ters vekili |
| Ev makinesinde Docker Compose | Genel sunucu üzerinden yönlendirin; Cloudflare Tunnel son çare olsun |
| Dizüstünde VS Code extension | Genel sunucu üzerinden yönlendirme |
| VM’de binary | VM veya ağ sınırında reverse proxy |
| Python/source dev server | Genellikle yalnızca localhost |
| Stdio mode | HTTP ağı yok; yerel MCP client kullanın |
