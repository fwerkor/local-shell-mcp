<!-- i18n-source-sha256: a3fdf9088031e6903b15497a3df881a8e6ed2f6f2b34dd4d0b68b0414a2ca81e -->
# Hızlı başlangıç

Bu kılavuz ilk runtime olarak Docker Compose, ilk client olarak ChatGPT kullanır. Bunlar bağımsız seçimlerdir: Docker, VS Code extension, binary, Python ve stdio runtime seçenekleridir; ChatGPT ve genel MCP client’ları client seçenekleridir. Tam harita için [runtime seçenekleri ve deployment modeli](../guides/deployment.md) bölümüne bakın.

## Gereksinimler

- Compose v2 ile Docker Engine.
- ChatGPT Web üzerinden bağlanacaksa herkese açık HTTPS endpoint.
- Özel bir workspace directory.
- Uzun ve rastgele OAuth admin PIN ile JWT secret.

!!! warning
    Bağlı model yapılandırılmış workspace üzerinde işlem yapabilir. Servisi disposable container veya VM içinde çalıştırın ve host-control resources bağlamayın.

## 1. Clone ve yapılandırma

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

`.env` dosyasını düzenleyin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. Sunucuyu başlatma

```bash
mkdir -p workspaces/default
docker compose up -d
```

Durumu kontrol edin:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Sağlıklı yanıt HTTP `200` döndürür.

## 3. HTTPS yayınlama

Cloudflare Tunnel sidecar için:

```bash
docker compose --profile tunnel up -d
```

Cloudflare Zero Trust içinde public hostname’i şuraya yönlendirin:

```text
http://local-shell-mcp:8765
```

Caddy, Nginx, Traefik, Nginx Proxy Manager veya başka bir reverse proxy için HTTPS traffic’i `127.0.0.1:8765` ya da container network address’e iletin.

## 4. ChatGPT bağlama

MCP endpoint’i kullanın:

```text
https://your-public-host.example.com/mcp
```

OAuth ve tool approval işlemini tamamlamak için [ChatGPT connector kılavuzunu](chatgpt-connector.md) izleyin.

## 5. Tool erişimini güvenle doğrulama

Modele şunu isteyin:

```text
local-shell-mcp kullan. Önce environment_get çağır, sonra workspace root’u listele. Henüz dosya değiştirme.
```

Beklenen read-only tools:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Sınırlandırılmış bir coding task ile başlama

İyi bir ilk task:

```text
Bu repository’yi incele, project layout’u özetle, açıksa mevcut test suite’i çalıştır ve dosyaları değiştirme.
```

Bağlantı doğrulandıktan sonra daha belirgin talimat verin:

```text
Başarısız testi düzelt. Önce ilgili dosyaları oku, en küçük patch’i yap, hedef testi çalıştır, sonra git diff göster. Ben onaylamadan commit yapma.
```

## Güncelleme

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Tunnel profile kullanıyorsanız:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

## Sonraki sayfalar

| İhtiyaç | Sayfa |
|---|---|
| runtime ve client seçimlerini anlama | [Runtime seçenekleri ve deployment modeli](../guides/deployment.md) |
| Docker Compose ile çalıştırma | [Docker Compose runtime](../installation/docker.md) |
| VS Code’dan çalıştırma | [VS Code extension runtime](../installation/vscode-extension.md) |
| release binary ile çalıştırma | [Standalone binary runtime](../installation/binary.md) |
| Python veya source checkout ile çalıştırma | [Python runtimes](../installation/python.md) |
| ChatGPT’yi client olarak ekleme | [ChatGPT connector](chatgpt-connector.md) |
| tools seçme ve daha iyi prompt yazma | [Kullanım kalıpları](../guides/usage-patterns.md) |
| HPC, NPU/GPU veya NAT makinesi bağlama | [Uzak workers](../guides/remote-workers.md) |
| Tüm MCP tools’u anlama | [Tools referansı](../reference/tools.md) |
