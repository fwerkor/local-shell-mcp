<!-- i18n-source-sha256: a40a962d4db93cc0aac03601ffd13b21ab3a504c9bff930ab4b8173c4cfa4537 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Kanallar ve modeller

## Bir kanal oluşturun.

Chat uygulamasındaki model seçiciyi açın ve “Kanal Yönetimi” bölümüne gidin. **Yeni kanal ekle** seçeneğini seçin, bağlantı türünü belirleyin, gerekli bilgileri girin ve kaydedin. Yeni bir sohbet için o kanaldan bir model seçin. Özel bir ajan kullanacaksanız, bunun yerine Ajan yapılandırmasında ilgili kanalı ve modeli seçin.

Kanallar kişisel sohbet ayarlarından ziyade Controller tarafından yönetilir. Kimlik doğrulaması yapılan ortamlarda, kanal yönetimi `admin:config` yetkisi gerektirir. Yöneticiler, API anahtarlarını sohbet kullanıcılarına dağıtmadan paylaşılan kanalları yapılandırabilirler.

![Gerçek kanal yapılandırma dialogında model kanalını ekleyin](../assets/chat/channel-settings.png)

Normal bir API kanalının adı, sağlayıcı protokolü, temel URL’si, kimlik bilgileri ve model kimlikleri vardır. Seçilen uç nokta için verilen API anahtarını kullanın; LSM hesabınızın şifresini değil. LSM, isteklerini Controller üzerinden gönderir; dizüstü bilgisayarınızdan çalışan bir URL, Controller üzerinden çalışmayabilir.

| Protokol | Örnek API temel URL’si | Kullanım |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | OpenAI ile uyumlu sohbet ağları ve yerel akıl yürütme sunucuları |
| OpenAI Responses | `https://api.openai.com/v1` | Yanıtları sunan bir ağ |
| Antropik yerli | `https://api.anthropic.com/v1` | Antropik mesajları destekleyen API’ler |
| Google Gemini yerlisi | `https://generativelanguage.googleapis.com/v1beta` | Gemini generateContent ile uyumlu API’ler |

Sağlayıcı tarafından gereken temel URL’leri kullanın; `/chat/completions` gibi tam bir istek URL’sini kopyalamayın. OpenAI uyumlu olduğunu iddia eden bir arayüz, Chat Completions’ı destekleyebilir, ancak Response’leri, araç çağrılarını, akış kullanımını, çok modlu girdileri veya akıl yürütme seçeneklerini desteklemeyebilir. Gerçekten hangi protokolü desteklediğini seçin. Örnek URL’ler sadece örneklerdir; bu, ücretsiz erişim veya mevcutluk garantisini içermez.

## Yerel ve özel uç noktalar

Controller üzerinden çalışan OpenAI uyumlu bir sunucu için, temel URL’nin `http://127.0.0.1:8080/v1` olabilir. Docker içinde çalışırken, loopback, fiziksel ana bilgisayarı değil, o konteyneri ifade eder. Controller’ın ağ adresinden ulaşılabilen bir adres kullanın. Yalnızca uzak bir Worker kaydı, onun akıl yürütme API’sinin erişilebilir olmasını sağlamaz.

Model URL doğrulayıcısı, HTTP dışında HTTPS gerektirir; ancak `localhost`, `127.0.0.1`, `::1` gibi loopback adreslerde HTTP kullanılabilir. LAN adresine veya Docker hizmet adına sahip bir HTTP uç noktası, HTTPS aracılığıyla erişilmelidir. Eski Hosted Chat özel uç noktası seçeneği uygulanamaz. Temel URL’lerde gömülü kimlik bilgileri, parçalar veya sorgu dizeleri bulunmamalıdır.

Uzak uç noktalarda TLS kullanılmalıdır. Erişim, yalnızca güvenilir özel ağlara sınırlanmalıdır. Ayrıca, model tanımlayıcıları da akıllı telefon sunucusuna karşı kontrol edilmelidir. API anahtarlarını asla metinlerde, ekran görüntülerinde veya yapılandırmalarda kullanmayın. Mevcut kanalı düzenlerken API anahtarını boş bırakın; böylece kaydedilen anahtar korunmuş olur. Anahtarsız bağlantıyı sadece hizmet bunu destekliyorsa kullanın.

## Çevre tarafından ayarlanan varsayılan değerler

Güçlendirilmiş OpenAI profili, uygulama başlatılmadan önce `LOCAL_SHELL_MCP_MODEL_BASE_URL` (veya `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL` ve `LOCAL_SHELL_MCP_MODEL_API_KEY` (veya `OPENAI_API_KEY`) ayarlarından oluşturulabilir. Güçlendirilmiş Anthropic ve Google profilleri ise sırasıyla `ANTHROPIC_API_KEY` ve `GOOGLE_KEY`/`GOOGLE_API_KEY` değerlerini okuyabilirler. Kaydedilen güçlendirilmiş profiller, çevresel olarak oluşturulan alternatiflerden daha üstün durumdadır; birden fazla bağımsız uç nokta için isimli kanallar kullanılmalıdır. Çevresel olarak ayarlanan varsayılan değerler, servis sırlarını korumanın bir alternatifi değildir.

## ChatGPT hesabının yetkilendirilmesi

Bu kanal, normal bir API anahtarı yerine, desteklenen ChatGPT hesabı yetkilendirme işlemini kullanır. Yetkilendirme işlemi, kanal yönetimi bölümünden başlar ve resmi yetkilendirme sayfasında oturum açılır. Yerel bir dağıtım durumunda, çağrı döngüsü otomatik olarak tamamlanabilir. Eğer tarayıcı, loopback dinleyicisine ulaşamıyorsa, çağrı döngüsünün tüm URL’sini adres çubuğundan kopyalayıp yetkilendirme dialogına yapıştırın. Bu manuel işlemde, loopback adresinde bir bağlantı sorunu beklenmektedir.

Geri çağırma URL'sini kimlik bilgisi olarak ele alın; asla sohbette göndermeyin veya yayımlamayın. Controller yetkilendirmeyi sunucuda saklar ve mümkün olduğunda kimlik bilgilerini yeniler. Hesabın süresi dolarsa veya erişim iptal edilirse yeniden yetkilendirin. Kullanılabilir modelleri, plan sınırlarını ve izin verilen kullanımı üst hesap hizmeti belirler; LSM ek abonelik kotası sağlamaz.

## Model keşfi ve bağlam sınırları

Model bilgilerini talep etmek için otomatik keşif özelliğini etkinleştirin. Controller, bu bilgileri periyodik olarak yeniler (şu an her on dakika bir kez); manuel olarak da bilgileri yenileyebilirsiniz. Başarısız olan keşiflerde, daha önce kaydedilen model verileri korunur. Eğer sağlayıcı uyumlu bir model listesi sunucusuna sahip değilse, keşif özelliğini devre dışı bırakın ve model tanımlamalarını manuel olarak girin.

Keşif, OpenCode Go/Zen'in iç içe `limit.context` alanı, OpenRouter'ın `context_length` alanı, vLLM'in `max_model_len` alanı ve Gemini'nin `inputTokenLimit` alanı gibi açık bağlam penceresi meta verilerini tanır. Yalnızca azami giriş uzunluğu bildiriliyorsa yedek değer olarak kullanılır; çıkış sınırları ve model adları bağlam kapasitesini belirlemez. İki bilgi de bildirilmezse bağlam penceresi bilinmez.

Her model için bağlam bilgilerini belirtin. Açıkça belirtilen değerler, keşfedilen meta verileri geçersiz kılar veya eksik olan değerleri doldurur. Editör, 1 ile 2.000.000 arası jeton kabul eder; bu bir yapılandırma aralığıdır ve sağlayıcının bu kapasiteyi desteklediğinin bir garantisi değildir. Kullandığınız sınırları belirleyin; bunu sunucu tarafı yapılandırmalarını ve modelin kendi sınırlarını göz önünde bulundurarak yapın.

## Örnek alma, mantık yürütme ve kullanım

Kanal/model varsayılanları, seçilen sağlayıcı tarafından desteklenen istek parametrelerini belirler. Sohbet kombinatörü, mevcut olduğunda mantık yürütme işlemlerini sunabilir. Farklı protokoller, örnek alma ve mantık yürütme işlemlerini farklı şekillerde gerçekleştirir; bazı seçenekler belirli bir model tarafından desteklenmeyebilir. Öncelikle sağlayıcının varsayılanlarını kullanın, ardından her seferinde bir ayarı değiştirin.

LSM, kesin akış anahtarı kullanımını talep edebilir ve sağlayıcı bu seçeneği reddettiğinde alternatif bir yöntem kullanabilir. Kullanım bilgilerini döndürmeyen bir uç nokta, kesin faturalama veya önbellek istatistikleri sağlayamaz. Kumulatif tüketim ile mevcut kapasite arasındaki farklar için [Memory and context](context.md) bölümüne bakınız.

## Kanalların değiştirilmesi ve silinmesi

Bir konuşma, seçilen modeli ve geçmiş verilerini korur. Uç noktaları değiştirirken veya bir sağlayıcının sorunlarını düzeltirken bu modeli kasıtlı olarak değiştirmelisiniz. Kullanımda olan bir kanalın adını değiştirmek, referansların korunması için sınırlıdır. Kullanımda olan bir kanalı silmek için ek onay gereklidir; geçmiş veriler korunur, ancak silinen kanala atıfta bulunan ajanlar ve sohbetler, işe yarar bir yerle değiştirmeyi seçmelidir.

Kanal ayarları, yalnızca tarayıcıda bulunabilen önceden belirlenmiş değerler değildir; bunlar sunucu tarafında yapılır. Kimlik bilgileri, normal kanal katalog yanıtları aracılığıyla verilmez. Controller durum dizinini ve yedeklerini, kimlik bilgilerini içeren veriler olarak koruyun.

## Bağlantı kontrol listesi

1. Yöneticinin API sunucusuna ulaşabildiğini ve TLS protokolünün geçerli olduğunu teyit edin.
2. Temel yol, protokol, kimlik bilgileri ve kesin model ID’sini teyit edin.
3. Keşfi yenileyin veya manuel olarak bir model seçin.
4. Kısa bir metin mesajı gönderin, ardından küçük bir aracı çağırın.
5. Yüksekli HTTP durumundaki hataları, zaman aşımı veya desteklenmeyen seçenekleri kontrol edin. Geçersiz kimlik bilgilerini tekrar tekrar denemeyin.

Oran sınırlamalarını, akış kesintilerini ve yetkilendirme hatalarını ele almak için [Administration and troubleshooting](administration.md) bölümüne bakınız.
