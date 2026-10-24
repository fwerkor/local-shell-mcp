<!-- i18n-source-sha256: f2dd1c4fffcc9783c739a12868fbcfa0023e0e3a783c8ba929f84107e3959e9a -->
# Barındırılan Sohbet (isteğe bağlı)

Barındırılan Sohbet, LSM'nin insan arayüzüne entegre edilmiş, kendi kendine barındırılan, BYOK sohbeti ve MCP Uygulamaları istemcisidir. Bu bir Mantıksal Oturum modu **değildir**: konuşmaların bağımsız kimlikleri vardır ve isteğe bağlı olarak mevcut bir LSM Mantıksal Oturumuna eklenebilir. ChatGPT ve diğer harici istemciler aynı LSM Oturumları ve araçlarıyla çalışmaya devam eder.

## Etkinleştir

Barındırılan Sohbet varsayılan olarak devre dışıdır. Ayarla:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Denetleyiciyi yeniden başlatın ve Web Kullanıcı Arayüzü / TUI seçicinin hemen altındaki **Barındırılan Sohbet**'i açın. Bu özellik aynı zamanda mobil üst çubuk girişine de sahiptir. Sohbet sunucusu mevcut LSM OAuth kimliğini ve kapsamlarını kullanır. Aynı denetleyici, modelin araç döngüsü tarafından kullanılan MCP sunucusunu çalıştırır; İşçiler yürütmeyi başlatamaz.

## Model profilleri

Adı, HTTPS OpenAI uyumlu API temel URL'si, model kimliği ve isteğe bağlı API Anahtarı olan bir profil oluşturmak/düzenlemek için **Model profilleri**'ni seçin. Birden fazla profil bir arada bulunabilir ve konuşmalar modelleri değiştirebilir.

Profiller, konuşmalar, tam mesaj geçmişi ve araç çağrısı sonuçları, yapılandırılmış LSM durumu arka ucu aracılığıyla **sunucuya kaydedilir**. Kapsamları kimliği doğrulanmış müdüre bağlıdır. API Anahtarı AES-GCM ile şifrelenir ve hiçbir zaman profil listesi veya profil ayrıntısı uç noktalarından döndürülmez. Tarayıcı deposunda saklanmaz, modele bilgi istemi olarak gönderilmez veya denetim günlüklerine dahil edilmez. Sohbet sunucusu bunu yalnızca seçilen model API'sine iletir.

İlk dosya destekli dağıtım, durum dizininde 0600 moduyla `hosted-chat-encryption-key` öğesini oluşturur. **Bu dosyayı durum verileriyle birlikte yedekleyin. Bu olmadan kayıtlı API Anahtarlarının şifresi çözülemez.** Denetleyici Redis, birden çok kopya veya dosya durumu olmayan başka bir arka uç kullanıyorsa kararlı, paylaşılan 32 baytlık URL güvenli bir base64 anahtarı yapılandırın:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

Şifrelenmiş profilleri taşımadan bu ayarı döndürmeyin. Kalıcı konuşmalar gerektiğinde bellek içi durum depolamayı kullanmayın.

Varsayılan olarak yalnızca DNS ana bilgisayar adlarına sahip HTTPS modeli uç noktaları kabul edilir; sunucu tarafı istek sahteciliği riskini azaltmak için yerel/özel uç noktalar ve HTTP reddedilir. Güvenilir bir özel model ağ geçidine bilinçli olarak ev sahipliği yapan yöneticiler aşağıdakileri tercih edebilir:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

Kullanıcılara dahili hizmetlerle iletişim kurma yetkisi verilmediği sürece, güvenilmeyen çok kullanıcılı Denetleyicide bunu etkinleştirmeyin.

## Konuşmalar ve MCP Uygulamaları

Kaydedilmiş bir model profilini kullanarak bir konuşma oluşturun. Gönderilen her sıra, sunucuya ait bir arka plan görevi haline gelir; tarayıcıyı kapatmak görevi iptal etmez. Tamamlanan metin ve araç çağrıları, model/araç adımları arasında kalıcı bir şekilde kontrol noktasına getirilir. Kesinti yapmak için açıkça durun. Kontrol Cihazı yeniden başlatıldığında, kesintiye uğrayan çalışmalar bu şekilde işaretlenir ve yeni bir turda devam ettirilebilir, ancak **bilinmeyen sonuçlu araç çağrıları hiçbir zaman otomatik olarak yeniden oynatılmaz**.

Konuşmanın tüm mesaj geçmişi depolama alanında saklanır. Bağlam boyutunu kontrol etmek için modele aynı anda yalnızca sınırlı bir son pencere gönderilir. Araç çağrıları, tüm sıradan araç izinleri ve denetim/ön kontrol davranışı korunarak, LSM'nin kimliği doğrulanmış MCP uç noktası aracılığıyla gönderilir.

LSM'nin mevcut `workspace_open` MCP Uygulamaları kaynağını yerleşik bir görünümde oluşturmak için **Live Workspace**'i açın. Ana bilgisayar, uygulama yaşam döngüsü, kimlik bilgilerinin yenilenmesi, araç çağrıları ve insandan temsilciye eylemler için `@modelcontextprotocol/ext-apps` köprüsünü kullanır. İkinci bir dosya yöneticisi, terminal, denetim veya iş kullanıcı arayüzü uygulanmaz.

İsteğe bağlı olarak eklenen `session_id`, Barındırılan Sohbetin mevcut bir Mantıksal Oturumu kullanmasına ve görüntülemesine olanak tanır; Oturumu yeniden sınıflandırmaz veya Barındırılan Sohbete sahiplik vermez. Sohbet görüşmesi tanımlayıcıları ve Mantıksal Oturum tanımlayıcıları ayrıdır.

## Sınırlar

- Model istekleri, araç çağırmayla birlikte OpenAI uyumlu Sohbet Tamamlamalarını kullanır; diğer sağlayıcı protokolleri bir bağdaştırıcı gerektirir.
- Tur başına korumalar model yinelemelerini ve takım çağrılarını sınırlar. Dayanıklı geçmişi kullanarak yeni bir dönemde daha uzun görevlere devam edilebilir.
- Sohbet konuşmasının silinmesi açıktır. Otomatik geçmiş tahliyesi gerçekleştirilmez.
- Denetleyicinin kendi MCP istemcisi tarafından ağ üzerinden erişilebilir olması ve tarayıcının LSM Live Workspace API için yetkilendirilmesi gerekir.
