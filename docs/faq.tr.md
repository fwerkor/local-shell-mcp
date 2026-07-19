# Sık sorulan sorular

Bu sayfa, sunucu sağlıklı olsa bile LSM arızası gibi görünebilen yaygın Client ve ters proxy sorunlarını açıklar.

## LSM yükseltmesinden sonra bazı araçlar neden ChatGPT'de kullanılamıyor?

### Belirtiler

- Yeni araçlar ChatGPT'de görünmez.
- ChatGPT kaldırılmış, yeniden adlandırılmış veya birleştirilmiş eski bir aracı çağırmaya devam eder.
- Araç vardır ancak ChatGPT eski bir girdi şeması gönderdiği için çağrı doğrulaması başarısız olur.
- LSM'yi yeniden başlatmak veya yeni bir konuşma açmak sorunu çözmez.

### Neden

ChatGPT, bir MCP App tarandığında, onaylandığında veya yayımlandığında mevcut olan araçların ve girdi şemalarının dondurulmuş anlık görüntüsünü saklayabilir. LSM sürümü `tools/list` değerini değiştirdiğinde bu görüntünün otomatik yenilenmesi garanti edilmez. Belgelenmiş bir sona erme süresine sahip kısa süreli bir önbellek değildir.

### Çözüm

=== "Geliştirici modu veya kişisel bağlantı"

    1. **ChatGPT Settings → Apps** bölümünü açın.
    2. LSM App'i açın ve araçları yeniden taramak için **Refresh** kullanın.
    3. Refresh yoksa eski App'i silin ve aynı MCP endpoint'i yeniden ekleyin.
    4. Güncel araç listesi kabul edildikten sonra yeni bir konuşma başlatın.

=== "ChatGPT Business'ta yayımlanmış App"

    Yayımlanmış özel bir App şu anda araçlarını veya metadata'sını yerinde güncelleyemez. Bir yönetici yeni App oluşturmalı, mevcut LSM endpoint'ini taramalı, yerine geçeni yayımlamalı ve eski App'i kullanımdan kaldırmalıdır.

=== "ChatGPT Enterprise veya Edu"

    Yönetici **Workspace Settings → Apps → LSM App → … → Action control → Refresh** bölümünü açabilir, farkları inceleyebilir ve gerektiğinde yeni action'ları etkinleştirebilir.

[Issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) ve [OpenAI MCP App belgelerine](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt) bakın.

## WebUI Nginx arkasında neden sürekli yeniden bağlanıyor?

### Belirtiler

- WebUI sayfası ve OAuth girişi normal yüklenir.
- TUI görünmez.
- Durum `Connecting`, `Connection error` ve `Reconnecting` arasında tekrar eder.
- `8765` portuna doğrudan bağlantı çalışır.

### Neden

Tarayıcı arayüzü yerel TUI'yi PTY WebSocket üzerinden işler. Varsayılan endpoint `/ui/ws`'dir; özel `ui_path` kullanıldığında `${ui_path}/ws` olur. Normal Nginx `proxy_pass`, WebSocket yükseltmesi için gereken hop-by-hop başlıklarını otomatik iletmez.

### Çözüm

HTTP/1.1'i etkinleştirin ve `Upgrade` ile `Connection` başlıklarını iletin:

```nginx
# map yönergesini http bloğuna yerleştirin.
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

Yapılandırmayı doğrulayın ve Nginx'i yeniden yükleyin:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Nginx Proxy Manager'da Proxy Host için **Websockets Support** seçeneğini etkinleştirin. Yeniden bağlanma sürerse Advanced bölümüne eşdeğer yükseltme başlıklarını ekleyin.

### Doğrulama

Tarayıcı geliştirici araçlarını açın, WebUI'yi yeniden yükleyin ve `/ui/ws` isteğini inceleyin. Çalışan bağlantı şunu döndürür:

```text
101 Switching Protocols
```

[Issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71) bölümüne bakın.
