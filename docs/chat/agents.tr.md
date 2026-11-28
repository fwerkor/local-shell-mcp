<!-- i18n-source-sha256: d33afa60bf803b367c950dbadf80fa77167568a970adcac204cdea7e9e965e45 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Ajanlar ve Beceriler

## Bir ajan oluşturmak için ne zaman hareket etmek gerekir?

Doğrudan model tabanlı sohbetler, tek seferlik sorunlar veya görevler için faydalıdır. Bir “Ajan”, tekrar tekrar seçilebilen bir yapılandırmadır; düzenli sohbetlerde kullanılabilir veya diğer ajanlara devredilebilir. Farklı ajanlar, farklı kanalları, modelleri, talimatları ve erişim politikalarını kullanabilirler. Hepsi aynı “Denetleyici”yi paylaşır; ancak mutlaka aynı bellek alanını veya araçları kullanmazlar.

## Bir ajanı yapılandırın.

WebUI aracılığıyla Ajanları yönetin, bir Ajan oluşturun, ona tanınabilir bir ad verin ve modelini seçin. Görevleri, istenen çıktıları, sınırlamaları ve doğrulama gereksinimlerini açıklayan talimatları yazın. İhtiyacı olan yetenekleri ayarlayın, ardından kaydedin ve yeni bir konuşma başlatın.

![Talimatlar, araçlar, onaylar ve Yetenek ayarlarıyla birlikte Ajan Oluşturucu](../assets/chat/agent-builder.png)

Örneğin, bir depo denetçisinin talimatları şöyle olabilir:

```text
Değişiklikleri mevcut ana sürümle karşılaştırın.
Sonuçlara varmadan önce repositoryyi ve test sonuçlarını inceleyin.
Dosyaları düzenlemeyin, commit’leri göndermeyin veya herhangi bir şeyi dağıtmayın.
Somut bulguları, yolları ve kanıtları ile birlikte bildirin.
```

Yönlendirmeler faydalı olsa da, bunlar yetki sınırları değildir. Makine erişimini sadece okunabilir olarak ayarlayın ve inceleme yapan kişinin herhangi bir şeyi değiştirmemesi gerekiyorsa, gereksiz dış MCP özelliklerini kullanmayın. Daha fazla bilgi için [Araçlar ve yetkiler](permissions.md) bölümüne bakın.

Farklı görevler için ayrı ayrı temsilciler kullanılmalıdır; örneğin kod incelemesi, uygulama ve işletme gibi görevler için. Her bir temsilciye mümkün olan en küçük yetki verilmeli ve rolüne uygun bir model sağlanmalıdır. Eğer bir temsilci çalışamıyorsa, referans verilen kanal ve modelin doğru olduğundan emin olunmalıdır. Ayrıca, alakasız ayarlar değiştirilmeden önce bu durum kontrol edilmelidir.

## Skills

Bir “Skill” paketi, tekrar kullanılabilir talimatlar ve ilgili dosyaları içerir. Genellikle bu dosyalar şu şekilde adlandırılır: `SKILL.md` WebUI üzerinden yetenekleri yönetin; ilgili yetenekleri etkinleştirin ve bunları Agent veya sohbet sistemine sunun. Model, gerektiğinde yetenek içeriğini keşfedip yükleyebilir. Bir yetenek, iş akışını tanımlayabilir, örnekler sunabilir veya betikler içerebilir. Ancak bu yetenekler otomatik olarak betikleri çalıştırmaz veya makineye ek izinler vermez.

İthal edilen becerileri etkinleştirmeden önce onları kontrol edin. Onların talimatlarını ve dosyalarını, diğer üçüncü parti kodlar veya komutlar gibi ele alın. Becerilerin adlarını ve açıklamalarını, modelin bunları kolayca bulabilmesi için yeterince belirgin tutun. Büyük referansları ayrı tutun ve küçük, bağımsız olarak kullanılabilir iş akışlarını tercih edin. Kontrolör tarafındaki kayıt sistemi ve araç çağrıları hakkında daha fazla bilgi için [Skills](../guides/skills.md) adresine bakınız.

Otomatik Skill ve hafıza bağlamı, her turda sistem komutlarının yeniden yazılmasını önlemek için kaydedilir. Skill’in kapsamındaki değişiklikler anında etkili olabilir; yeni düzenlenen otomatik bağlamı test ederken yeni bir konuşma kullanılmalıdır. Kasıtlı olarak yüklenen Skill, başlangıçtaki otomatik bağlamdan farklıdır.

## Delegasyon ve alt ajanlar

Ajanlar, bu yeteneğe sahip olduklarında, sınırlı işleri alt ajanlara devredebilirler. Bir çocuk, yapılandırılmış bir ajan kullanabilir ve kendi konuşma sürecini kendi başına yönetebilir. Ebeveyn ise görevi koordine eder, çocuğun sonucunu okur ve kaydedilen çocuk sürecini devam ettirebilir. Çocuğun aktivitelerini ebeveynden izleyebilirsiniz; ancak bu görünüm bağımsız olarak düzenlenebilecek bir sohbet değildir.

Bağımsız inceleme, ayrı dosya alanları veya farklı hipotezlerin incelenmesi gibi ayrılabilir görevler için delegasyon kullanılmalıdır. Alt ajanlara somut bir hedef, kapsam ve beklenen sonuç verilmelidir. Ebeveynin kullanamadığı bir makineye veya “MCP” hizmetine aynı anda yazma işlemleri yapılmamalıdır; alt ajanın onay politikası, ebeveynin politikasını zayıflatmamalıdır. Alt ajan görevleri, model jetonlarını ve zamanı bağımsız olarak kullanabilir; bu nedenle maliyet ve ilerlemeyi değerlendirirken onların aktivitelerini ve sonuçlarını inceleyin.

Delegasyon, ebeveynin yetkilendirdiği sınırlar içinde kalmalıdır. Ebeveynin kullanamadığı bir makineye veya MCP hizmetlerine erişim verilmemelidir. Çocuk görevlerinin izlenmesi ve sonuçlarının değerlendirilmesi gerekiyor. Çocuk görevleri, model jetonlarını ve zamanı bağımsız olarak kullanabilir; bu nedenle onların aktivitelerini ve sonuçlarını değerlendirirken dikkatli olunmalıdır.

## Araçlar, eylemler ve ürünler

Agent Builder, kullanılabilir araç kütüphanesini ve gelişmiş yapılandırmalarını sunar. Sadece ihtiyacınız olan özellikleri seçin. Bir OpenAPI şemasıyla tanımlanan bir HTTP işlemi için, işlemi bağlamadan önce uç noktayı, kimlik doğrulama gerekliliklerini ve izin verilen işlemleri inceleyin. İşlemler kendi kimlik doğrulamalarını kullanabilir; bir makine yetkisi, üçüncü taraf API kimlik bilgilerini onaylamaz veya iptal etmez. Uzaktan yapılan değişikliklerin tamamlanmasından önce işlem sonucunu kontrol edin.

Oluşturulan UI içeriği için, [Konuşmalar ve projeler](conversations.md) bölümünde anlatıldığı gibi, artifactların görüntülenmesi ayarlarını yapın. Oluşturulan kodlar, Controllerın güvenilir bir uzantısı değildir.

## Pratik Agent şablonları

- **Sadece okunabilir araştırmacı:** Gösterge kayıtlarını incele, kanıtları karşılaştır, nedenleri belirle; hiçbir değişiklik yapılmamalı.
- **Uygulama Ajanı:** Bir depoyu düzenlemek, hedeflenen testleri gerçekleştirmek, farklılıkları ve çözülmemiş hataları raporlamak gerekir. Eğer gerekiyorsa, hassas işlemler için onay gereklidir.
- **Monitör Ajanı:** Belirlenen makineleri kontrol eder ve durumları, hataları ve ölçülen ilerlemeyi raporlar. Yetkili olmadıkça işleri yeniden başlatmaz.
- **Araştırma Aracı:** Ağ aramasını sağlar, orijinal belgeleri belirtir, kanıtları çıkarımlardan ayırır ve yalnızca gerektiğinde makine araçlarını kullanır.

Bu şablonlar, yerleşik ayarlar değil; sadece talimatlardır. Her bir ajanın gerçek izinlerini ve yeteneklerini, onun üstleneceği görevlere uygun şekilde yapılandırın.
