<!-- i18n-source-sha256: 91fa7e8e41354be2761864ffe05d1efb85063953c79a40065ad61661cc15b836 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Yönetim ve sorun giderme

## Dağıtım mimarisi

WebUI ön ucu, Python’daki Controller aracılığıyla sunulur. Bu Controller, REST ve MCP uç noktalarıyla aynı konumda bulunur. Varsayılan veritabanı yapısı SQLitedır. Yayımlanan binlerce dosya içinde derlenmiş ön ucu bileşenleri de bulunmaktadır. Kaynak kodlardan bir program oluşturmak için JavaScript geliştirme araçları gereklidir; yüklü bir Controller aracılığıyla bunu yapmak mümkün değildir. Node.js, MongoDB, Meilisearch ve ayrı olarak dağıtılan LibreChat arka uçlarına ihtiyaç yoktur.

[Hızlı Başlangıç için bilgiler](../getting-started/quickstart.md) ve [Yapılandırma referansları](../reference/configuration.md) kullanılabilir. Kaynak derlemeler için ise [WebUI ile derleme talimatlarına](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) bakınız.

## Dağıtımın güvenli bir şekilde gerçekleştirilmesi

Güvenilir bir HTTPS ters proxy veya tünel kullanın; ayrıca kimlik doğrulama ve güçlü şifreler de gereklidir. Controller’ı uygun bir konteyner veya VM sınırları içinde tutun. Gelen erişimleri sınırlayın ve çıkış için gerekli olan kimlik bilgilerini koruyun. Kimlik doğrulaması yapılmayan bir işlem uç noktasını kamu internetinde açık bırakmayın.

Bir proxy, verilerin tamamlanana kadar beklemeden akışını desteklemeli ve WebSocket uyumluluğunu da gerektiren arayüzler için destek sağlamalıdır. Uzun süreli model ve araç talepleri için uygun okuma/sadece bekleme süreleri kullanılmalı ve istenen yükleyebilecek boyutlar da dikkate alınmalıdır. Yapılandırılan public URL’nin, tarayıcının orijini ve OAuth çağrılarıyla uyumlu olması sağlanmalıdır. TLS hatalarını düzeltmek için genel olarak sertifika kontrollerini devre dışı bırakmaktan kaçınılmalıdır.

İstekler, Controller üzerinden gelir ve modelde görünen mesajlar, ekler ve diğer veriler seçilen upstream API’ye gönderilebilir. Gizli içerikleri kullanmadan önce sağlayıcının veri işleme kurallarını dikkatlice inceleyin. Ayrıca dışarıdaki MCP sırlarını ve Worker davet tokalarını da koruyun.

## Durum, yedekleme ve yükseltme

Varsayılan durum dizini, yapılandırılmış çalışma alanının altındaki `.local-shell-mcp` adlı klasördür. `LOCAL_SHELL_MCP_STATE_DIR` değiştirilebilir. Paylaşılan veritabanı ise `lsm.sqlite3` şeklindedir. Sohbetler, projeler, ayarlar, Ajanlar, bellek, zaman çizelgeleri ve işlemlerin durumları sunucuda saklanır. Ekler, çalışma alanı dosyaları ve diğer veriler ise veritabanının dışında tutulabilir.

Tüm durum klasörünü geri yüklein. Dışarıda yapılandırılmış durumları da geri yüklein. Dağıtım ortamı/şifreler ve ilgili çalışma alanı dosyalarını da geri yüklein. Yedeklemeleri hassas olarak ele alın. Sadece veritabanının yedeği, ekleri veya yapılandırmaları eksik bırakabilir. Düzenli bir Controller kullanın veya tutarlı bir SQLite yedekleme mekanizması kullanın. Sadece canlı SQLite ana veritabanı dosyasını kopyalamak, işlenmiş WAL içeriğini eksik bırakmayabilir. Yedeklemeleri, izole bir test dağıtımına geri yükleerek kontrol edin.

Yükseltmeden önce, mevcut sürümü, çalışma yolunu, yapılandırmaları, durumun yerini ve aktif işleri kaydedin. İlgili işlemleri durdurun veya güvenli bir şekilde temizleyin, aynı kurulumu yükseltin ve kimlik doğrulamasını, sohbet geçmişini, model oluşturma işlemlerini, akış işlemlerini, Workersları ve planlanan görevleri doğrulayın. Eski durumdan SQLite ile yapılan migrasyon, başlangıçta desteklenir; migrasyonu doğrulamadan önce eski dosyaları saklayın. Üretim veri dizinini boş bir test dizinine değiştirmeyin.

Rollback işlemi, veritabanı migrasyonu sonucunda değişen durumları sadece değiştirmek anlamına gelmez. Gerekli olduğunda uyumlu bir durumu geri getirin ve aynı canlı depoda iki ayrı yapılandırılmış Controller’ın çalıştırılmasından kaçının.

## Başarısız olan sohbet işlemini teşhis edin.

| Belirti/semptomlar. | Öncelikle kontrol edin. |
|---|---|
| UI’yi yükleyemiyoruz. | Controller süreci, ön uç paketi, doğru URL, proxy ve kimlik doğrulama. |
| Model eksik. | Kanal yapılandırması, model tanımlama, model ID, hesap yetkilendirmesi. |
| Sunucudan gelen HTTP 401/403 yanıtları. | API anahtarı/hesap, sunucunun izinleri, seçilen kanal ve protokol. |
| HTTP 429 | Aşırı yük sınırları, eşzamanlı istekler, hesap/plan durumları. |
| HTTP 400/413/422 | İsteklerin uyumluluğu, girdi/context boyutu, ek belgelerin sınırları, model parametreleri. |
| HTTP 5xx veya zaman aşımı | Sağlayıcının sağlığı, ağ durumları, modelin hizmet kapasitesi, proxy zaman aşımları |
| Çıktı akışının durması | Yeniden bağlantı/yeniden yükleme; üretim durumunu ve detaylı hataları incelemek |
| Aracın kullanılamıyor olması | Özelliklerin etkinleştirilmesi, Ajan yetenekleri, Makine ACL’leri, OAuth kapsamları, Kontrolör anahtarları |
| Çalışanlar çevrimdışı durumda | Çalışanların kaydı, dışa yapılan bağlantılar, heartbeat işlemleri ve Controller günlükleri |
| Onay/ sorunların beklenmesi | Konuşmayı açmak ve istenen işlemi incelemek |
| Programın çalışmaması | Etkin durum, zaman dilimi, Ajan/kanal, hedef, kaydedilmiş yetkilendirme, son çalıştırma |

Lütfen tüm HTTP hatalarının aynı hizmetten kaynaklandığını varsaymayın. LSM giriş hatası, üst düzey model API hataları, dışarıdan gelen MCP hataları ve işlemci iletişim hatalarını ayırt edin. Detaylı hataları ve ilgili Controller loglarını kontrol edin; anahtarları, bearer token’ları ve çağrı yanıt URL’lerini paylaşmadan önce gizleyin.

## Sağlayıcıların yeniden deneme ve kurtarma işlemleri

Model yanıtı başlamadan önce geçici bağlantı hataları ve belirli HTTP hataları (408, 429, 500, 502, 503, 504) sınırlı bekleme süreleriyle yeniden denenebilir. Güncel normal yeniden deneme gecikmeleri 1, 2, 4, 8, 16, 30, 30 ve 30 saniyedir (ilk istekten sonra sekiz yeniden deneme). HTTP Retry-After gecikmeyi 120 saniyeye kadar uzatabilir; bazı akış hataları rastgele sapma ekler. Yeniden deneme sınırı tüm sohbetin ömrüne değil, her bir model isteğine uygulanır. Bağlam sıkıştırmanın kendi kurtarma yolu vardır. Kredilerin tükenmesi nedeniyle hız sınırı, sağlayıcı kotayı yenileyene kadar devam edebilir. Otomatik yeniden deneme başarıyı garanti etmez ve aboneliği sınırsız yapmaz.

Ara sıra meydana gelen kesintiler, ilk yanıt verme olayından önceki hatalardan farklıdır. Kısmen gerçekleştirilmiş bir işlemin otomatik olarak yeniden çalıştırılmasına güvenmeyin. Yeniden denemeden önce kaydedilen verileri ve dış durumları kontrol edin. Eğer işlem hala devam ediyorsa, aynı işi tekrar yapmak yerine yeniden bağlantı kurun. Eğer işlem başarısız olduysa, chat kurtarma/yeniden deneme kontrollerini uygun şekilde kullanın; ya da orijinal işlemin devam edememesi durumunda yeni bir chat başlatın.

Bağlamla ilgili sorunlar, normal model oluşturma hatalarından ayrı olarak incelenmelidir. Etkin bağlam sınırlarını, model uyumluluğunu, aşırı büyüklükteki sonuçları ve kullanılabilir kotaları kontrol edin. Daha fazla bilgi için [Bellek ve bağlam bölümüne bakın](context.md).

## Hata raporunda nelerin yer alması gerektiği

Raporun içinde LSM sürümünü, kurulum yöntemini, işletim sistemini, model protokolünü, güvenli hale getirilmiş uç nokta türünü, model kimliğini, yaklaşık zamanı, üretim adımlarını, ilgili sohbet/çalışma durumunu ve detaylı hata bilgilerini belirtin. Uzak bir sorun söz konusuysa, Worker sürümünü, makine adını ve heartbeat/poll durumunu da ekleyin. Mümkünse küçük bir üretim örneği de ekleyin; asla API anahtarlarını, OAuth tokenlerini, özel bilgileri veya gereksiz kişisel verileri göndermeyin.
