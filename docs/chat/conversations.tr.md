<!-- i18n-source-sha256: af41013e98ff8fbebf496514fd0034d1c97f3177d7e73f77f7c0c21f6022047b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Konuşmalar ve projeler

## Bir sohbet oluşturun ve devam ettirin.

Yeni bir konuşma açın, bir kanal/modeller veya Ajan seçin ve bir mesaj girin. Sohbet, Controller üzerinde gerçekleşir ve güncellemeler tarayıcıya aktarılır. Sayfayı yenilemek veya bir sekmeyi kapatmak, işlemin iptal edilmesi anlamına gelmez. Bir işlemin devamını durdurmak için “dur” düğmesini kullanabilirsiniz ve başka bir işlem yapmadan önce sonucu kontrol edebilirsiniz.

Kurtarılan sohbetler, sahip oldukları model/agent ilişkisini korur. Farklı bir model istiyorsanız, bunu kasıtlı olarak değiştirebilirsiniz. Bir sohbet, mantıksal bir oturum değildir; burada kullanıcı ve model mesajları saklanır. Oysa mantıksal bir oturumda ise aracın görev hedefleri, ilerleme durumu ve planlar yer alır. Uzun süreli görevler devredilirken ilgili kimlik bilgilerini de koruyun.

## İşleri düzenleyin ve bulun.

Projeler kullanılarak, birbiriyle ilişkili konuşmalar gruplandırılabilir ve ortak makine izinleri belirlenir. Bir proje, birden fazla ayrı sohbeti içerebilir. Farklı konuşmaların tüm bağlamını paylaştığı varsayılmasından kaçınarak, uygun projeye sohbetleri yerleştirin veya yeni sohbetler oluşturun. Aktif proje, Agent’a konuşmanın nasıl organize edildiğini bildirebilir.

Etiketler, konuşmaları sınıflandırır; mesajlar ise belirli mesajlara işaret eder ve faydalı sonuçlara geri dönmeyi sağlar. Bunlar, bir konuşmayı sabit tutmaktan farklıdır. Kullanıcı dostu bir ara yüz oluşturmak için sohbet başlıklarını, arama özelliklerini, arşivleme ve okunmamış mesajları gösterme özelliklerini kullanın.

Arşivleme işlemi, bir konuşmayı normal listeden çıkarır, ancak kaydedilen geçmişi silmez. Gerekirse arşiv arayüzünden bu konuşmayı geri getirebilirsiniz. Bir konuşmayı silmek yıkıcı bir işlemdir; bu yüzden silme işlemini arşivleme yerine kullanmayın. Mevcut uygulama, SQLite kullanarak konuşma durumunu saklar; eski sıkıştırılmış Hosted Chat arşiv formatını varsaymayın.

## Mesaj işlemleri ve görevlerin yürütülmesi

Mevcut mesaj kontrolleri, mesajın ve o anki çalışma durumuna bağlıdır. Gerekirse bir turu düzenleyin veya tekrar deneyin. Gerekli olmadığı zaman ise seçilen kullanıcı/asistan turunu silin. Silme işlemi, kaydedilen konuşma geçmişini değiştirir ve daha sonraki durumları etkileyebilir. Bu işlemler sonucunda shell komutları, uzaktan yapılan yazılar, Git ile yapılan güncellemeler veya diğer dış etkiler geri alınamaz.

Başarısız olan bir işlemin tekrarlanması sırasında, detaylı hataları okuyun ve öncelikle zaten tamamlanan işlemleri inceleyin. Eğer yazma işlemi, bağlantının kesilmesinden önce başarılı olmuşsa, işlemi tekrarlamadan önce dış durumunu kontrol edin. Eğer başka bir mesaj beklemekteyse veya bir işlem zaten devam ediyorsa, aynı anda birden fazla işlemin gerçekleştiğini varsaymak yerine, görünen kontrolleri ve durum bilgilerini kullanın. “Beklemekte olan mesajlar” paneli, bekleyen işlemleri incelemenizi sağlar; “Yönlendirme kontrolü” ise, şu an yürütülmekte olan işlemler tamamlandıktan sonra güvenli bir şekilde yönlendirme yapmaya çalışır. Her iki işlem de zaten tamamlanmış işlemlerin etkilerini geri alamaz.

## Ekler, önizlemeler ve diğer veriler

Ekler kontrolünü kullanarak dosyaları veya desteklenen görüntüleri yükleyebilirsiniz. Yüklemelerde, tek bir eklerin boyutu 32 MiB’ye kadar sınırlıdır. Ayrıca, dağıtım/yönlendirme işlemleri nedeniyle daha küçük bir sınırlama da olabilir. Yüklenen dosyalar Controller üzerinde saklanır ve model tarafından erişilebilir hale getirilir. Görüntülerin yorumlanması için ise, görüntü girişlerini kabul edebilen bir model ve sağlayıcı gereklidir. Bir dosyanın yüklenmesi, yerel veya uzaktan erişilebilecek diğer dosyalara erişim izni vermez.

Oluşturulan bir dosyayı talep ederken, dosyanın bulunacağı yeri, formatını ve içeriğini belirtin. Sonuçların mevcut olduğundan emin olunduktan sonra onu paylaşın. Chat’ten indirilebilen veya önizlenebilen ekleri/verileri kullanabilirsiniz. Worker üzerinde oluşturulan dosyaların Controllera aktarılması gerekebilir; veya uygun bir dosya bağlantısı kullanılabilir. Daha fazla bilgi için lütfen [Dosya bağlantıları](../guides/file-links.md) bölümüne bakın.

Artifact renderleme işlemi, React, HTML, SVG, Markdown ve Mermaid gibi öğeleri sadece kod olarak değil, aynı zamanda bir yan panelde de gösterebilir. Agent artifact ayarlarında “Normal” seçeneği standart talimatları kullanır; “shadcn/ui” ise bileşen/kütüphane ile ilgili talimatlar ekler. “Özel” seçeneği ise, yerleşik artifact talimatları olmadan bile öğelerin renderlemesini sağlar. Üretilen kodları veya görüntülenen içerikleri güvenilmez olarak kabul edin; bunları önizleme dışında kullanmadan önce mutlaka inceleyin. Dosya tabanlı Office önizlemeleri ve indirmeler, üretilen UI öğelerinden farklıdır.

Seçilen model sağlayıcısına göndermeye yetkin olmadığınız kimlik bilgilerini, özel anahtarları veya belgeleri yüklemeyin. Eklerin silinmesi ve sohbet içeriklerinin silinmesi, makinedeki kaynak dosyaların silinmesinden farklıdır.

## Tercihler

Sohbet ve kullanıcı tercihleri, örneğin araçların açık/kapalı olması ve klavye kısayolları gibi özellikler, WebUI aracılığıyla yönetilir ve uygulandığı sunucuda saklanır. Klavye davranışlarını ayarlamak için Ayarlar bölümünü açın; mesaj göndermek ile satır sonu işlemlerini ayırt edin. Sohbetle ilgili araçların açık/kapalı olması gibi özellikleri, Agent yetkililerinden ayrı olarak ayarlayın. Daha fazla bilgi için [Araçlar ve yetkiler](permissions.md) ve [Bellek ve bağlam](context.md) bölümlerine bakın.

### Otomatik konuşma adlandırma

Ayarlar → Sohbet → Konuşmalar bölümünde otomatik adlandırmayı kapatmayı, yeni sohbetleri bir kez adlandırmayı veya tamamlanan her yanıttan sonra yeniden adlandırmayı seçin. Varsayılan olarak yeni sohbetler kendi konuşma modeliyle bir kez adlandırılır. Yapılandırılmış bir kanaldan başka bir model de seçebilirsiniz. Adlandırma yalnızca ana yanıt tamamlandıktan sonra çalışır; başarısız veya iptal edilen yanıtlar bunu tetiklemez. Başlık, görevi kullanıcının dilinde kısaca açıklar. Adlandırma isteği sohbet bağlamından ayrıdır ve sohbet mesajı eklemez.
