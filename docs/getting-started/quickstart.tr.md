<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Hızlı başlangıç

Bu kılavuz bir LSM Denetleyicisini başlatır ve tarayıcı arayüzünü açar. [unified web workspace](web-workspace.md) önerilen günlük deneyimdir; ayrı olarak konuşlandırılmış, isteğe bağlı bir sohbet yığınıdır. ChatGPT, Gemini ve diğer harici MCP istemcileri aynı Denetleyiciye bağlanabilir. Bkz. [runtime choices and deployment model](../guides/deployment.md).

Önerilen yöntem, [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest) üzerinden **tek dosyalık Controller çalıştırılabilirini** kullanmaktır. Python, Docker veya kaynak checkout gerekmez. Örnek **Linux x86_64** içindir; diğerleri: [ikili kurulum](../installation/binary.md).

## Gereksinimler

- Uygun çalıştırılabilir dosya ve `curl` (Linux x86_64 örneği).
- Uzak kullanıcılar veya harici MCP istemcileri için gerektiğinde genel HTTPS.
- Ayrı ve sınırlı çalışma alanı.
- Güçlü OAuth yönetici PIN’i ve rastgele JWT sırrı.

!!! warning
    Bağlı model yapılandırılmış workspace üzerinde işlem yapabilir. Servisi disposable container veya VM içinde çalıştırın ve host-control resources bağlamayın.

## 1. Çalıştırılabilir dosyayı indirme ve yapılandırma

Tek dosyayı indirin ve JWT sırrı üretin:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

`.env` oluşturup örnek PIN ve JWT sırrını değiştirin (`openssl rand -hex 32`). İkili `.env` dosyasını **otomatik yüklemez**.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Sunucuyu başlatma

İndirilen dosyayı doğrudan başlatın:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Durumu başka bir terminalde kontrol edin:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Sağlıklı yanıt HTTP `200` döndürür. Kalıcı çalıştırma için servis yöneticisi kullanın.

## 3. HTTPS yayınlama

Uzak erişim için genel sunucu veya HTTPS ters proxy (Caddy, Nginx, Traefik) kullanın. Dosya transferleri dahil tüm siteyi şu adrese yönlendirin:

```text
http://127.0.0.1:8765
```

HTTPS bağlantısını denetleyin:

```bash
curl -i https://your-public-host.example.com/healthz
```

Dosya aktarımı için **Cloudflare Tunnel önerilmez**: istemci yüklemeleri yavaş olabilir. OAuth açık kalmak kaydıyla genel sunucu veya normal proxy/port yönlendirme tercih edin. Alternatif: [Docker](../installation/docker.md).

## 4. Tarayıcı çalışma alanını açın

Denetleyici girişini açın:

```text
https://herkese açık-ana makineniz.example.com/ui
```

Sohbet, projeler ve entegre kontrol sayfaları için [unified web workspace guide](web-workspace.md)'i takip edin. Orijinal hafif WebUI, sohbet yüklü olmadığında kullanılabilir.

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

Yeni sürüm dosyasını değiştirip Controller’ı yeniden başlatın:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Docker Compose için konteyneri güncelleyin; kaynak kurulum: [Python](../installation/python.md).

```bash
docker compose pull
docker compose up -d
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
| Birleşik sohbet ve kontrol arayüzünü kullanın | [Unified web workspace](web-workspace.md) |
| Gemini Spark'ı istemci olarak ekleyin | [Gemini Custom Apps](gemini-spark.md) |
| ChatGPT’yi client olarak ekleme | [ChatGPT connector](chatgpt-connector.md) |
| tools seçme ve daha iyi prompt yazma | [Kullanım kalıpları](../guides/usage-patterns.md) |
| HPC, NPU/GPU veya NAT makinesi bağlama | [Uzak workers](../guides/remote-workers.md) |
| Tüm MCP tools’u anlama | [Tools referansı](../reference/tools.md) |
