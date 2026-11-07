<!-- i18n-source-sha256: e75cf6e4ffc3fe904983cd63b99b43c2877c4bdd99174b2d4a96393eff5d9e3f -->
# Birleşik web çalışma alanı

**Birleşik LSM web çalışma alanı**, local-shell-mcp'yi günlük olarak kullanmanın önerilen yoludur. Yapay zeka sohbetini, proje geçmişini ve LSM kontrol düzlemini değiştirilmiş, satıcı tarafından sunulan LibreChat ön ucunu temel alan tek bir duyarlı arayüzde birleştirir. [ChatGPT](chatgpt-connector.md) veya [Gemini](gemini-spark.md) gibi harici MCP istemcilerini hâlâ bağlayabilirsiniz.

Çalışma alanı **kendi kendine barındırılır ve kurulumu isteğe bağlıdır**: ayrı bir web hizmetidir; minimum Denetleyici görüntüsünün, bağımsız yürütülebilir dosyanın veya uzak Çalışan paketinin parçası değildir. Yalnızca denetleyici dağıtımları orijinal tarayıcı kullanıcı arayüzünü ve OpenTUI'yi korur.

## Çalışma alanında neler var?

| Alan | Ne yapabilirsin |
|---|---|
| Sohbet ve projeler | Yapılandırılmış bir model seçin, konuşmalar oluşturun, projeleri düzenleyin, geçmiş sohbetleri bulun ve konuşmaları arşivleyin. Geçmiş sunucuda kalır. |
| Denetleyiciye genel bakış | Sağlığı, son etkinlikleri ve bağlı makineleri görüntüleyin. |
| Dosyalar | Yerel veya uzak dosyalara göz atın ve yönetin. |
| Terminaller | Denetleyici veya İşçilerdeki kalıcı terminallerle çalışın. |
| Masaüstü | Uzak GUI oturumlarını inceleyin ve kontrol edin. |
| Oturumlar | Dayanıklı LSM görevlerini ve bunların yaşam döngüsünü inceleyin. |
| Uzaktan kumandalar | Giden İşçileri bağlayın ve yönetin. |
| Denetim | Model kaynaklı araç etkinliğini inceleyin. |
| İç içe MCP | LSM'nin arkasındaki harici MCP sunucularını kaydedin, düzenleyin, etkinleştirin, devre dışı bırakın, yenileyin ve kaldırın. |

Denetleyici rotaları `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` ve `/control/audit`'dir. Sohbet `/c/new`'de açılır. LSM MCP yöneticisi **LSM'nin iç içe MCP kaydını** kontrol eder; LibreChat'te ikinci bir kayıt defteri oluşturmaz.

## İsteğe bağlı sohbet yığınını dağıtın

1. Uygun şekilde izole edilmiş bir çalışma alanı ve kalıcı `file` veya `redis` durum depolama alanı olan OAuth ile [Install and start an LSM Controller](quickstart.md). Docker Compose'u yükleyin ve depoyu web yığınını çalıştıran ana bilgisayara kopyalayın.
2. Denetleyici için `https://lsm.example.org` ve çalışma alanı için `https://chat.example.org` gibi **aynı sitede iki HTTPS kaynağı** sağlayın. Sohbet hizmeti güvenilmeyen bir ağda doğrudan kullanıma sunulmaz.
3. `openssl rand -hex 32` ile bir köprü sırrı oluşturun. Bu ortam değişkenlerini **Denetleyici hizmetinde** bu sırrı kullanarak yapılandırın ve ardından hizmeti yeniden başlatın:

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. Depo kontrolünde isteğe bağlı web yığınını yapılandırın. Özel bir ortam dosyası kullanın veya aşağıda gösterilen değerleri dışa aktarın; benzersiz güçlü sırlar oluşturun ve bunları taahhüt etmeyin:

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Özel yapılandırmayı oluşturun, ardından ayrı olarak dağıtılan sohbet yığınını oluşturun ve başlatın:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

Kök Docker Compose dağıtımını kullanırken yukarıdaki Denetleyici değişkenleri `.env` köküne aittir ve kaba iletilir. Sohbet hizmeti değerleri, kabuk aktarımları veya özel bir ortam dosyası aracılığıyla sağlanabilir. Denetleyici kapsayıcısına, adı geçen Docker ağında `http://local-shell-mcp:8765` adresindeki sohbet kapsayıcısından erişilebilir olması gerekir. Sohbet HTTPS kaynağına `127.0.0.1:3080` proxy bağlantı noktasını ters çevirin, harici ana bilgisayarı koruyun ve depodaki [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md)'yi izleyin. Web yığını Node.js, MongoDB, Meilisearch ve SearXNG'yi çalıştırır; İşçiler kategorisine **dahil değildir**. Bu ayrı dağıtım, depo kökündeki düz bir `docker compose up -d` tarafından başlatılmaz.

## Oturum açın ve sohbeti kullanın

1. `https://lsm.example.org/ui`'i açın, **LSM Denetleyici** oturum açma bilgilerini kullanarak kimlik doğrulaması yapın ve web çalışma alanına tek seferlik geçişi takip edin. İkinci bir LibreChat kullanıcı hesabı oluşturmazsınız.
2. Bir model sağlayıcı yapılandırın. İsteğe bağlı web yığını, OpenAI, Anthropic ve Google kimlik bilgilerini varsayılan olarak `user_provided` olarak gösterir: sohbet uç noktası ayarlarında kendi sağlayıcı anahtarınızı girin veya başlamadan önce sohbet Compose ortamında `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` veya `GOOGLE_KEY`'i ayarlayın. Sohbette desteklenen bir model seçin. **LSM, modelleri veya API kredilerini içermez.** Gemini Spark'ın harici MCP bağlantısı, Gemini modelini burada yapılandırmaktan farklıdır.
3. Bir konuşma oluşturun. Web araması ve LSM araçları, Denetleyici izinlerine bağlı olarak varsayılan olarak etkindir. Konuşma başına **Web**, **LSM**, **Harici MCP** ve **Bellek** kontrollerini gerektiği gibi kullanın.
4. Salt okunur bir istekle başlayın: "Denetleyici durumunu kontrol edin ve çalışma alanı kökünü listeleyin. Dosyaları değiştirmeyin."
5. Doğrudan inceleme ve kontrol için **Dosyalar**, **Terminaller**, **Masaüstü**, **Oturumlar**, **Uzaktan Kumandalar** veya **Denetim**'e gidin.

Sohbet yüklemeleri (32 MiB'a kadar) Denetleyici çalışma alanı altında depolanır ve bunların mutlak yolları modele sağlanır. Tarayıcı yüklemeleri ek dosya izinleri vermez. Modele yönelik araç çağrıları, LSM yetkilendirmesi, denetimi ve uzak çalışan yönlendiricisinden geçer.

## Harici MCP, güvenlik ve veriler

Yuvalanmış harici MCP sunucularını yönetmek için çalışma alanı MCP kenar çubuğunu kullanın. Bu, ayrı özel ortam değişkenleri ve istek başlıkları dahil olmak üzere yerel stdio sunucularını ve HTTP sunucularını destekler. Sırlar tarayıcıya döndürülmez. **Harici MCP** sohbet düğmesi, iç içe geçmiş araçların aranmasına, incelenmesine ve çağrılmasına olanak tanır; yerel LSM araçları devre dışı bırakıldığında `mcp_manage` modelini vermez. Kullanıcı arayüzü yönetimi normal Denetleyici yetkilendirmesi ile korunur.

Sohbet mesajları, projeler ve arşivler sunucu tarafında web yığınının MongoDB'sinde depolanır; arama Meilisearch'ü kullanır. Denetleyici ayrıca araç izinlerine, Çalışan kimliklerine, oturum durumuna ve denetime sahiptir. Tüm geçmişi saklamanız gerekiyorsa her iki veri deposunu da yedekleyin. Sohbet arka ucu, LSM'nin oturum açma bilgileri altında tek kullanıcılıdır; dahili API'sini veya veritabanlarını kamuya ifşa etmeyin.

Kullanıcı arayüzü üst düzey bir uygulamadır; **iframe değil**. İsteğe bağlı sohbet hizmeti yapılandırılmamışsa `/ui`, orijinal LSM WebUI'yi sunmaya devam eder. Yerel OpenTUI ve harici istemciler desteklenmeye devam eder.

## Sorun giderme

- **Yönlendirme orijinal kullanıcı arayüzünde kalır:** `LOCAL_SHELL_MCP_LIBRECHAT_URL`'i, kalıcı Denetleyici durumu arka ucunu ve web yığınının HTTPS ters proxy'sini kontrol edin.
- **Oturum açma veya aktarma başarısız olursa:** her iki tarafta da aynı 32 baytlık veya daha uzun köprü sırrını doğrulayın; aynı site kaynakları, HTTPS ve sunucu saatleri ile eşleşsin.
- **Sohbet yükleniyor ancak yanıtlanamıyor:** Gerçek bir model uç noktası veya API kimlik bilgisi ayarlayın ve sohbet kapsayıcısı günlüklerini kontrol edin.
- **MCP araçları eksik:** Denetleyici kapsamlarını ve görüşme başına geçişleri doğrulayın; iç içe geçmiş sunucu kayıt defteri LibreChat MCP veritabanından ayrıdır.
- **Dosyalar veya oturumlar boş görünüyor:** sohbetin doğru Denetleyiciye ve çalışma alanına ulaştığını doğrulayın ve API kimlik doğrulama günlüklerini inceleyin.

Uygulama ayrıntıları ve güncellemeleri için [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) ve [human interface guide](../guides/human-interface.md)'e bakın.
