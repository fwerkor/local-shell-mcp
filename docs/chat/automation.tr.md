<!-- i18n-source-sha256: 01c14c19cf5addf99299993b57542259bcb40bbfb13600758b516a86c89e716b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Hedefler, planlanan sohbetler ve uzun süreli işler

## Doğru mekanizmayı seçin.

| Mekanizma | Amaç/Hedef |
|---|---|
| Sıradan sohbet oluşturma | Mevcut komutlara yanıt verme, ayrıca araç çağrıları da dahil olmak üzere… |
| Sohbet hedefleri belirleme | Modelin dönüş noktalarında aktif bir planın devam ettirilmesi |
| Planlanmış sohbetler | Kaydedilmiş komutlarla bir Agent oluşturun ve bunu düzenli aralıklarla gerçekleştirin. |
| Kalıcı görevler veya terminal işlemleri | Tek bir model talebi olmaksızın komutların çalıştırılması |
| Alt ajanlar | Sınırlı bir görevini başka bir Ajan iş parçacığına devretmek. |

Planlanan bir sohbet, sürekli çalışan bir işlem değildir. Mantıksal bir oturum ise bir konuşma veya işletim sistemi süreci değildir. Bir sohbetin iptal edilmesi, onun tarafından başlatılan tüm işlemlerin sonlanması anlamına gelmez.

## Sohbet hedefleri belirleme

Uzun süren bir iş için, Agent’dan somut bir hedef belirlemesini ve Logical Session araçlarını kullanarak bir plan oluşturmasını isteyin. Bu plan, adımları ve bunların durumlarını kaydeder. Chat çalışma ortamı, yeni bir kullanıcı girişi veya dışarıdan gelen MCP Live Workspace’ın bekleme süresini beklemeden, aktif bir planı devam ettirebilir.

Planı ve ilerleme durumunu kontrol edin. Mümkün olan hedef kontrollerini kullanarak planın devamını durdurun, tekrar başlatın veya iptal edin. Planın devam etmesi için aktif bir plan ve uygun bir çalışma süresi gereklidir; tamamlanmış, engellenmiş veya iptal edilmiş bir planın devam etmemesi gerekir. İlerleme olmadan tekrarlanan aynı yanıtlar, sonsuz döngü yerine bir duraklama anlamına gelir (şu an üç değişmeyen sınır sonrasında böyle bir durum oluşuyor). Devam etmeden önce asıl engeli çözün.

Tamamlanma kriterlerini belirleyin. Örneğin: bir depoyu incelemek, bir düzeltme yapmak, ilgili testleri gerçekleştirmek ve herhangi bir başarısızlık durumunda bunları raporlamak gibi. Ajan’dan, sadece kendi planına göre başarılı olduğunu belirtmek yerine, tam olarak hangi komitelerin yapıldığı ve test sonuçlarının ne olduğunu kaydetmesini isteyin.

Dışarıdan gelen MCP istemcisinin hedef mekanizması ayrıdır. Logical Session ve Live Workspace’ın aktarım işlemleri hakkında daha fazla bilgi için lütfen [Human interface](../guides/human-interface.md) bölümüne bakınız.

## Bir zamanlanmış sohbet oluşturun.

![Devre dışı örnek plan içeren zamanlanmış sohbetler kenar çubuğu](../assets/chat/scheduled-chats.png)

Planlanan sohbet yönetimini açın. Açıklamalı bir adla bir plan oluşturun; ayrıca kaydedilmiş bir ajan, uyarılar, zaman dilimi ve sıklık da belirleyin. Sohbetin hedefini seçin; isteğe bağlı olarak yeni bir sohbet için bir proje de seçebilirsiniz. Planı kaydedip etkinleştirin. Konfigürasyonu doğrulamak için manuel çalıştırma kontrolünü kullanın.

Desteklenen zamanlamalar arasında saatlik, günlük, haftalık, beş alanlı kronometreler ve sürekli yürütme işlemleri bulunmaktadır. Sürekli yürütme işlemi, belirlenen gecikten sonra devam eder; sıfır gecikme durumunda ise sağlayıcı ve makine yükü artar. Normal tekrarlayan zamanlamalar için en az beş dakikalık bir aralık gereklidir. `Asia/Shanghai` veya `UTC` gibi belirli bir IANA zaman dilimini kullanın; kaydettikten sonra bir sonraki çalışmayı kontrol edin.

Hafta içi 09:00 için cron örneği:

```text
0 9 * * 1-5
```

Bu durumda, seçilen zaman dilimi kullanılır; ancak bu, mutlaka Controller’ın kendi sistem zaman dilimidir. Seçilen zaman diliminin “gündönümü” özelliğini uygulayıp uygulamadığını kontrol edin.

## Konuşma hedefleri

- **Her çalıştırmada yeni sohbet:** Her bir durum için ayrı bir konuşma başlatın; bu, ayrı raporlar oluşturmak için faydalıdır.
- **Aynı sohbeti yeniden kullan:** İlk seferde bir konuşma oluşturun ve bunu daha sonraki durumlar için de kullanın. Bu, toplam süreç izlemesi açısından faydalıdır.
- **Mevcut bir sohbeti kullan:** Planlanan sırayla konuşulacak olan mevcut sohbetleri seçin.

Yeniden kullanılan veya mevcut olan bir konuşma, daha da gelişebilir ve sıkıştırılması gerekebilir. Tarihsel bağlamın gerekli olmadığı durumlarda bağımsız sohbetler seçilmelidir. Planlanan işlemler, seçilen Ajan ve model kanalının hâlâ kullanılabilir olup olmadığına bağlıdır.

## Dikkatsiz bırakılan yetkililer/izinler

Zamanlanmış yürütme Controller'a aittir ve tarayıcı oturum açma belirtecini saklamak yerine kayıtlı yetkilendirilmiş kapsam adlarını kullanır. Gerektiğinde yetkilendirmek için zamanlamayı kaydedin veya elle çalıştırın. Belirlenen Agent'ın makine izinleri geçerlidir; sıradan proje veya sohbet makine ayarları zamanlamanın makine ilkesi değildir. Controller kısıtlamaları, kayıtlı yetkilendirme, araç yetenekleri ve araç onayları geçerliliğini korur.

Kimlik doğrulaması gerektiren harici MCP sunucularında etkileşimli oturum açma, gözetimsiz yürütme için yenilenebilir izin bulunduğu anlamına gelmez. Zamanlama arayüzü yeniden kimlik doğrulama veya gözetimsiz erişim gerektiğini bildirirse, zamanlamayı etkinleştirmeden önce sunucuya özgü kimlik bilgilerini düzeltin ya da bağımlılığı kaldırın. Tarayıcı belirteçlerini bunun yerine kullanmayın.

İzleme amacıyla yalnızca okunabilir bir ajan kullanılmalıdır. Kabul edilebilir hedefler, istenen çıktılar ve önlenmesi gereken durumlar açıkça belirtilmelidir. Eğer planlanan bir işlem insanın müdahalesine veya onayına ihtiyaç duyuyorsa, bekleyen işlemleri kontrol edin; izinsiz gerçekleştirilen işlemlerin sınırsız erişim anlamına geldiğini varsaymayın. İzleme işlemi için örnek bir mesaj şu şekildedir:

```text
Belirlenen eğitim işlemini ve ilgili logları inceleyin.
Şu anki adım, kayıp, verimlilik, tahmini varış zamanı ve herhangi yeni hataları rapor edin.
Dosyaları değiştirmeyin, işlemi yeniden başlatmayın veya yeni işlemler yapmayın.
Eğer veriler mevcut değilse, kesin nedenini belirtin.
```

## Yaşam döngüsü ve kurtarma işlemleri

Yönetici, programların zamanlamasını ve işlemlerin gerçekleşme durumunu tutarak, tekrarlanan başlatmaları önler. Tarayıcı pencerelerinin açık kalması gerekmez. Kaçırılan işlemlerin her zaman yeniden yapıldığı veya Yönetici’nin yeniden başlatılması sonucunda tüm dış işlemlerin devam ettiği varsayılmamalıdır. Durdurma süresi sonrasında en son çalıştırılan işlemleri, bir sonraki çalıştırma durumunu ve ilgili sohbetleri kontrol edin.

Gelecekteki otomatik işlemleri önlemek için bir zamanlayıcıyı devre dışı bırakın. Zaten çalışan bir zamanlayıcıyı ayrıca kontrol edin; gelecekteki zamanlayıcıların durdurulması, gerçekleşen bir işlemin veya görevin iptal edildiği anlamına gelmez. Artık gerekli olmayan zamanlayıcıları kaldırın ve gereksiz Agent izinlerini iptal edin.

WebUI Ajanı tarafından oluşturulan bir iş veya terminal, normal model yanıtlarının tamamlanmasından sonra bile çalışmaya devam edebilir. Sadece bir Controller’ın yeniden başlatılması, bu işlemin sonlandırılmasını garanti etmez. Ajanın sahip olduğu işlerin iptal edilmesi için açık bir şekilde işin sonlandırılması, makinenin yetkilerinin kaybolması veya yetkinin süresinin dolması gibi durumlar gereklidir. Eğer işçi çevrimdışıysa, işin sonlandırılması beklenen bir durumdur. İşin veya terminalin durumu kontrol edildikten sonra ancak işin sonlandırıldığı söylenebilir. Ajan, kendi işlerini/shell’lerini yalnızca WebUI aracılığıyla gönderebilir veya durdurabilir. Dış MCP istemciler ise kendi özelliklerini korurlar.

Ajanın arka plan araçları ve alt ajan görevleri, kendi yaşam döngilerine sahiptir. Bir sonuç, işlem tamamlandıktan sonra bile teslim edilmemiş olabilir. Konuşmanın arka plan görev paneline bakın ve sonucu toplayın; veya yapılandırılan uyarı sisteminin ana görevleri devam ettirmesine izin verin. Sonucun henüz görünmediği için tekrarlanan bir göreve başlamayın.

Tek bir araç talebinden daha uzun süre devam edecek komutlar için, LSM tarafından izlenen işlemleri veya kalıcı terminalleri kullanın. Sonuçları bir log dosyasına kaydedin, işlem kimliklerini belirtin ve gerçek ilerlemeyi kontrol edin. Daha fazla bilgi için [Kullanım desenleri](../guides/usage-patterns.md) bölümüne bakınız.
