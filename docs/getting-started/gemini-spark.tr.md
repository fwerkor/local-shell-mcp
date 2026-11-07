<!-- i18n-source-sha256: b7c3dfd7dc21a498f8410a88a8a52094ca0349856dfa43d267e3fe7bb273685a -->
# Gemini Spark'ı / Özel Uygulamaları Bağlayın

Gemini'nin **özel bağlantılı uygulamalar** özelliği (daha önce **Spark** olarak tanımlanıyordu) uygun bir Gemini kullanıcısının uzak bir MCP sunucusuna bağlanmasına olanak tanır. LSM, MCP uç noktasını sağlayabilir. Bu, [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) ve diğer MCP istemcilerine **alternatif bir istemci bağlantısıdır**; LSM Denetleyicisinin yerini almaz veya dağıtmaz.

Google şu anda özel uygulamaları **Amerika Birleşik Devletleri'nde **kişisel Google Hesabı** ile oturum açmış ve **Etkinliği Etkin Tut** ile oturum açmış 18 yaş ve üstü kullanıcılar** ile sınırlandırmaktadır. Bu özellik **İngilizce** olarak mevcuttur. Bağlantıların Gemini web uygulamasında oluşturulması gerekir, ancak bağlı uygulamalar daha sonra mobil cihazlarda kullanılabilir. Kullanılabilirlik ve kullanıcı arayüzü etiketleri değişebilir; [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137)'e bakın.

## Bağlanmadan önce

- Örneğin [Docker Compose](../installation/docker.md) ile bir LSM çalışma zamanı başlatın ve durumunu doğrulayın.
- MCP uç noktasını **herkese açık HTTPS** üzerinden gösterin ve OAuth'u etkin tutun.
- Denetleyicinin kimlik doğrulama ayrıntılarını öğrenin ve yalnızca ihtiyacınız olan kapsamları onaylayın.
- Kısıtlı bir çalışma alanı veya kapsayıcı kullanın. Gemini dosyalar, makineler ve terminaller üzerinde gerçek efektlere sahip işlemler talep edebilir.

İkizler'e girilecek son nokta:

```text
https://your-public-host.example.com/mcp
```

Web kullanıcı arayüzüne (`/ui`), LibreChat URL'sine veya site kaynağına `/mcp` olmadan girmeyin. Genel dağıtımlar, bağlantı hatalarını gidermek için kimlik doğrulamayı devre dışı bırakmamalıdır.

## İkizler'de bağlanın

1. Bir bilgisayarda [Gemini](https://gemini.google.com/)'i açın ve uygun bir kişisel hesapla oturum açın.
2. **Ayarlar ve yardım → Bağlı Uygulamalar**'ı açın. Mevcut arayüze bağlı olarak **Kişisel Zeka → Bağlantılı Uygulamalar** altında olabilir.
3. **Özel uygulamalar** altında **Özel uygulama ekle**'yi seçin veya özel uygulama URL'si alanını kullanın.
4. LSM HTTPS `/mcp` URL'sini yapıştırın ve **İleri**'yi seçin.
5. OAuth ve izin akışını LSM Denetleyicisi ile tamamlayın. LSM, OAuth keşfini ve dinamik istemci kaydını destekler. Gemini bunun yerine manuel OAuth istemci kimlik bilgileri isterse, devam etmeden önce gelişmiş seçeneklerini ve LSM OAuth kurulumunuzu kontrol edin.
6. Gemini görüşmesinde `@` yazın ve LSM aracı istemek için bağlı özel uygulamayı seçin.

Şununla başlayın: "Ortamı incelemek ve çalışma alanı dosyalarını listelemek için bağlı LSM uygulamasını kullanın. Hiçbir şeyi değiştirmeyin." Yazma işlemlerini denemeden önce araç sonuçlarını ve Denetleyici denetimini kontrol edin.

## Sınırlamalar ve sorun giderme

- **Özel uygulama seçeneği yok:** hesabı, bölgeyi, yaşı, dili ve Keep Activity uygunluğunu onaylayın. Bu bir LSM yapılandırma hatası değil, Gemini tarafı kullanılabilirlik kısıtlamasıdır.
- **URL reddedildi:** dışarıdan erişilebilen bir HTTPS `/mcp` uç noktası kullanın; OAuth keşfini ve ters proxy'nizi kontrol edin.
- **OAuth başarısız oluyor:** LSM yetkilendirme ekranını, istemci kaydını, geri arama URL'sini ve verilen kapsamları kontrol edin. Kimliği doğrulanmamış bir MCP uç noktası yayınlamayın.
- **Bir araç eksik veya arızalı:** İstemci tarafı MCP aracı/şema desteği farklılık gösterebilir. Basit bir salt okunur aramayı deneyin ve LSM denetimini ve günlüklerini inceleyin; Gemini istemci özelliklerinin tamamıyla tam uyumluluk garanti edilmez.
- **Bağlantıyı kesme:** artık gerekmediğinde LSM'yi devre dışı bırakmak, bağlantısını kaldırmak veya kaldırmak için **Bağlı Uygulamalar**'a geri dönün.

Google'ın [official guide](https://support.google.com/gemini/answer/17209137)'i, en son Özel Uygulama akışını ve kullanılabilirliğini açıklar. Bunun yerine yerel CLI tabanlı Gemini entegrasyonu için [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/)'e bakın. LSM [ChatGPT connector tutorial](chatgpt-connector.md) bağımsız olarak kullanılabilir durumda kalır.
