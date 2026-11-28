<!-- i18n-source-sha256: 8ec601aa8e9c57afef769d8346567626355ccf88e122e3296735b7af3639c562 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat

LSM WebUI Chat, Controller’da yer alan, kendi sunucularında çalışan bir AI ajanı çalışma alanıdır. Kendi model uç noktanızı veya desteklenen bir hesabı kullanabilirsiniz; böylece model, kendi araçlarınız ve makinelerinizle bağlantı kurabilir. Dışarıdan herhangi bir MCP istemcisine ihtiyaç yoktur. Dış istemciler yine de aynı Controller’a bağımsız olarak bağlanabilirler.

## Parçaların nasıl bir araya getirildiği

- **Controller:** Tarayıcı uygulamasını barındıran, istekleri işleyen, araçların çalıştırılmasını sağlayan, zamanlamayı yöneten ve kalıcı durumları saklayan Python servisi.
- **Kanal:** Kendi kimlik bilgileri, protokolü, modellerin listesi ve ayarları olan bir model API bağlantısı veya desteklenen bir hesap yetkilendirmesi.
- **Model:** Bir kanal içindeki modelin tanımlayıcısıdır. İki farklı kanalda aynı tanımlayıcı kullanılması, aynı uç noktanın ifade edilmediği anlamına gelmez.
- **Ajan:** Bir modeli, talimatları, araçları, yetenekleri ve izinleri bir araya getiren, tekrar kullanılabilir bir yapıdır.
- **Konuşma:** Kaydedilen mesajlar, ayarlar, işlemlerin geçmişi ve model/agent ilişkisi.
- **Proje:** Ortak ayarlarla birlikte gerçekleştirilen bir dizi konuşmaların toplamı.
- **Worker:** Dışa bağlı bir yürütme hedefidir. Bu, bir model sağlayıcısı veya ayrı bir sohbet sunucusu değildir.
- **Logical Session:** Araç tarafında gerçekleşen görevlerin tanımlayıcısıdır; bu, bir konuşma kimliğinden farklıdır. Bir sohbet, hedefleri, ilerlemeyi ve araç üzerindeki işleri takip etmek için bunu kullanabilir.

Bu model API’si, modelin görünür olduğu bağlamı ve araçların sonuçlarını alır. Controller, yetkili araçları çalıştırır; model ise doğrudan bir Worker ile bağlantı kurmaz veya model API anahtarını kullanmaz. Tarayıcı, konuşmayı sunar ve Controllerı kontrol eder.

## Bir rehber seçin.

| İstiyorum ki… | Okuyun |
|---|---|
| Kurulumu yapın, giriş yapın ve ilk görevleri çalıştırın. | [Hızlı başlangıç için bilgiler](../getting-started/web-workspace.md) |
| Bir model API’sini veya hesabını bağlayın. | [Kanallar ve modeller](channels.md) |
| Yeniden kullanılabilir ajanlar oluşturun ve işleri başkalarına devredin. | [Ajanlar ve yetenekler](agents.md) |
| Chat’ları, dosyaları ve projeleri yönetin. | [Konuşmalar](conversations.md) |
| Geçmiş bilgileri ve bağlamı anlayın. | [Hafıza ve bağlam](context.md) |
| Yürütmeyi kısıtlayın ve MCP araçlarını yönetin. | [Araçlar ve yetkilendirmeler](permissions.md) |
| Uzun süreli görevleri ve zamanlamayı yönetmek. | [Hedefler ve otomasyon](automation.md) |
| Web’de arama yapmak ve belgeleri okumak. | [Ağ araması](../guides/webui-network-search.md) |
| Bir dağıtımı çalıştırmak, yedeklemek ve hata gidermek. | [Yönetim ve sorun giderme](administration.md) |

## Temel prensipler.

Belirlenmiş bir makinede, sınırlı kapsamlı ve sadece okuma amaçlı bir işlem başlatın. Değişiklikler yapmadan önce araçın çıktısını kontrol edin. Bir model yanlış olabilir; ancak araç başarılı olsa bile. Model kimlik bilgileri, sohbet depoları, makine erişimi ve araç onayları ayrı konulardır; birini değiştirmeniz diğerini otomatik olarak etkilemez. Özellikle, kamuya açık bir sohbet uç noktası, uzaktan kontrol düzeneği olarak korunmalıdır.

Dış MCP istemci yolunu için lütfen [İstemci bağlantısı](../clients/connectivity.md) bölümüne bakın. Temel araç argümanları için lütfen [Araçlar referansı](../reference/tools.md) bölümüne bakın.
