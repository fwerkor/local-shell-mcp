<!-- i18n-source-sha256: e5ebd5f8cfb42332f4e38d63eabe47a6274ceacf919130202203bd85917f3469 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Araçlar, makineler ve yetkilendirme.

## Yetkilendirme katmanları.

Listelenen bir araç, onu çalıştırma iznini garanti etmez. Etkili yetkilendirme işlemleri, Kontrolör kısıtlamaları, kimlik doğrulanmış kullanıcıların yetkileri, makine politikaları, Ajan yetenekleri ve araç onayı gibi faktörleri içerir. Sadece talimatlar yeterli değildir; erişim için mutlaka gerekli olan izinler de gereklidir.

Kayıtlı makineler, yerel Kontrolör hedefi de dahil olmak üzere, sohbet makinesi politikası için varsayılan olarak okuma/yazma özelliğini kullanır. Hassas dağıtımlarda bu varsayımın uygulanmasını sınırlayın. Bilinmeyen makine adlarına herhangi bir hak verilmez. Kontrolör, yerel çalışmayı veya uzaktan çalışanları bağımsız olarak devre dışı bırakabilir.

## Makine erişimi

| Erişim | Anlamı |
|---|---|
| Yok | Makine işlemleri kullanılamaz. |
| Salt okunur | Sadece okuma yeteneğine sahip işlemler izin verilir; rastgele kabuk/Python işlemleri okuma-yazma yeteneğine sahip işlemler değildir. |
| Okuma/yazma | Yetkili kişilerin okuma, değiştirme ve işleme işlemlerini yapmasına izin verilir; ancak diğer kısıtlamalar da geçerlidir. |
| Devral | Belirli bir üst düzey varsayımı kullanılmalıdır; açıkça belirtilen bir değişiklik yapılmamalıdır. |

![Bir konuşmada makinenin yetkilendirme ve onay modu](../assets/chat/machine-permissions.png)

Makine izinleri denetimlerinde genel varsayılanları, proje ve sohbet bazındaki geçersiz kılma ayarlarını belirleyin. Sohbet ayarları proje ayarlarına, proje ayarları da genel varsayılanlara önceliklidir. Agent, makine başına veya kendi varsayılan ilkesiyle erişimi daha da kısıtlayabilir; açık Agent izinleri kimliği doğrulanmış öznenin veya Controller'ın kısıtlamalarını aşamaz.

Örnek: Genel okuma/yazma ilkesi, projede salt okunur ayarı ve Agent için okuma/yazma izni varsa, sohbet ilkesi açıkça değiştirmedikçe ilgili projenin sohbetinde erişim salt okunurdur. Sohbetin okuma/yazma ayarı yine de Agent'ın salt okunur sınırını aşamaz.

İsimli bir ajan ile planlanan bir işlemde, o ajanın makine politikaları kullanılır ve kaydedilen yürütme kapsamları devralınmaz. Daha detaylı bilgi için [Hedefler ve otomasyon](automation.md) bölümüne bakınız. Beklemeden yapılan işlemler için ayrı bir ajan kullanılmalıdır.

## Aracın onaylanması

| Moda | Davranışlar |
|---|---|
| Otomatik | Yetkili araçların çağrıları, ayrı bir politika gerektirmediği sürece, ek bir onay işlemi olmadan gerçekleşir. |
| Riskli operasyonları gözden geçirin | Yönetici, tehlikeli olarak sınıflandırılan işlemlerin incelenmesini talep ediyor. Bu işlemler arasında keyfi olarak kullanılan komutlar ve birçok dışa bağlı çağrı da bulunuyor. |
| Tüm araçları inceleyin | Normal araç çağrıları için onay alınması gerekmektedir. |

Sohbet onay ayarları Agent'ın ve genel varsayılanların ayarlarını devralabilir. Mevcut açık ret veya onay kuralları geçerliliğini korur. Bir alt Agent, üst Agent'ın onay modunu gevşetemez. Onay izinlerden bağımsızdır: reddedilmiş bir makine eylemini onaylamak makineye erişim sağlamaz.

Onay vermeden önce, ilgili argümanları, hedefleri ve olası yan etkileri dikkatlice gözden geçirin. İzlenmeyen bir iş akışı için, Agent ve onay politikalarını dikkatli bir şekilde ayarlayın; insanların onay vermesi, işlerin ilerlemesini geciktirebilir. Sadece uyarıları kaldırmak için erişimi genişletmeyin.

## Yerli ve harici MCP araçları

Yerel araçlar, Controller ve kayıtlı Workers üzerinde LSM aracılığıyla çalışır. Araç kaydı, dosya işlemleri, kabuk ve işler, tarayıcı ve GUI işlemleri, uzaktan keşif, mantıksal oturumlar ve diğer işlevleri içerir. Tam argüman şemaları için [Araçlar referansları](../reference/tools.md)’na bakın; makinelerle bağlantı kurmak için ise [Uzak çalışanlar](../guides/remote-workers.md)’ye başvurun.

WebUI içindeki iç içe geçmiş MCP sunucularını yönetin. Desteklenen yapılandırmalar arasında yerel standart giriş/çıkış ve uzaktan HTTP iletişimi bulunmaktadır. Ayrıca, sunucuya özgü çevre değişkenleri veya başlıklar da kullanılabilir. Chat uygulamasında ve ilgili Agent programında dışarıdan gelen MCP işlevlerini etkinleştirin. Agent, mevcut dış araçları keşfedebilir, inceleyebilir ve çağırabilir; ancak yetkilendirme ve araç onayı konuları hâlâ geçerlidir.

Harici bir MCP aracı yerel makine ACL'lerinden bağımsız çalışabilir: yerel makine erişimi devre dışı olsa bile harici bir uzak API kaynakları değiştirebilir. Harici hizmetin izinlerini ve kimlik bilgilerini ayrı ayrı inceleyin. Hassas dosyalar barındıran bir Controller'a güvenilmeyen stdio sunucuları kurmayın.

## Kullanıcıdan ve özelliklerin geçici olarak devre dışı bırakılmasından haberdar olun.

“Ask User” özelliği, bir Ajan’ın tahmin yaparak değil, yapılandırılmış insan girdisi talep etmesine olanak tanır. Cevap vermek için sunulan sorular kullanılır. Bu, bilgi isteme işlemidir; reddedilen bir işlemi geçmek için izin isteme işlemi değildir. Görev beklenen durumdaysa, Ajan’a belirsizlikleri nasıl ele alacağına dair talimatlar verilir ve henüz tamamlanmamış olan etkileşimler incelenir.

Besteci, ağ arama, harici MCP ve bellek gibi özellikleri kontrol edebileceğimizi gösteriyor. Bu özellikler, modelin hangi yeteneklerin kullanılacağını belirler; bu özellikler yetkilendirme işlemlerinden bağımsızdır. Bir özelliği devre dışı bırakmak, geçmişte elde edilen sonuçları silmez. Ağ arama özelliği varsayılan olarak aktif durumdadır ve [Ağ arama](../guides/webui-network-search.md) bölümünde belirtildiği gibi yalnızca okunabilir web araçlarını kullanır.

## Denetim ve doğrulama

Chat üzerindeki araç çağrılarını ve bunların sonuçlarını inceleyin; arızaların teşhis edilmesinde daraltılmış detayları açın. Kontrolörün denetim günlüğü, yerel araçların aktivitelerini kaydeder; işler/seslolar ise devam eden işlemleri gösterir. Başarılı bir API yanıtı, aracın bir sonuç döndürdüğü anlamına gelir; ancak bu, istenen dışsal işlemin hedefine ulaştığı anlamına gelmez. Yazdırma işlemlerini, uzaktan yapılan işlerin durumunu ve dağıtımın sağlığını bağımsız olarak kontrol edin. Daha fazla bilgi için lütfen [Denetim günlüğü](../guides/audit-log.md)’ye bakın.
