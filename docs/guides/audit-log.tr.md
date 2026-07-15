# Denetim günlüğü

Bu sayfa “Denetim günlüğü” senaryosunu açıklar ve sitenin ortak Runtime/Client yapısını korur.

## Genel bakış

Runtime, sunucu sürecinin nasıl çalıştığını ve hangi workspace’i kontrol ettiğini belirler. Client, ChatGPT veya başka bir MCP istemcisinin nasıl bağlandığını belirler. Docker, VS Code eklentisi, bağımsız ikililer, Python/pipx/kaynak kurulumları ve stdio Runtime seçenekleridir; ChatGPT bağlayıcısı, genel HTTP MCP istemcisi ve stdio MCP istemcisi Client bağlantılarıdır.

## Ne zaman kullanılır

- Seçilen Runtime veya Client yolu bu başlıkla eşleştiğinde bu sayfayı kullanın.
- Workspace kökü, public base URL, MCP endpoint, kimlik doğrulama modu ve kullanılabilir host araçlarını tutarlı tutun.
- ChatGPT web/app için `/mcp` ile biten bir HTTPS MCP endpoint yayımlayın.
- Yerel MCP istemcileri için istemci desteğine göre HTTP localhost veya `local-shell-mcp --mode stdio` kullanın.

## Adımlar

1. Önce Runtime kurulum sayfasını seçin.
2. Runtime’ı başlatın ve HTTP modu kullanılıyorsa `/healthz` değerini doğrulayın.
3. Sonra Client bağlantı sayfasını seçin.
4. Client içinde MCP endpoint veya stdio komutunu kaydedin.
5. Etkin workspace ve ayarları doğrulamak için `environment_info` çağırın.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Doğrulama

- `environment_info` Runtime ayarlarını ve workspace’i doğrular.
- `tree_view` görünen dosyaları doğrular.
- `run_shell_tool` komut ortamını doğrular.

## Notlar

Küçük ve doğrulanabilir adımları tercih edin: incele, düzenle, diff kontrol et, test et, tara ve commit yap. Büyük görevler de denetlenebilir araç çağrılarına bölünmelidir.
