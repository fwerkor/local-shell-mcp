<!-- i18n-source-sha256: 01cf883cb71925e93fabc21d32315ef8c869ee2ea548e54a0347e2f6b730a327 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat Hızlı Başlangıç

Birleşik LSM web çalışma alanı, AI sohbet özelliklerini, projeleri, Ajanları ve Kontrolörün işlevsel sayfalarını bir araya getirir. Bu sistem, Python Kontrolörü tarafından yönetilir ve kimlik doğrulama ve SQLite veritabanı kullanır. Ayrı bir sohbet sunucusuna ihtiyaç yoktur. [ChatGPT](chatgpt-connector.md) ve [Gemini](gemini-spark.md) gibi dış MCP istemcileri de hâlâ desteklenmektedir.

## 1. Controller'ı başlatın

Tercih ettiğiniz çalışma ortamına göre [kurulum kılavuzunu](quickstart.md) takip edin. WebUI’nin etkin olduğundan emin olun ve kalıcı depolama alanını kullanın. Aşağıdakiler normal varsayılan değerlerdir:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

Hizmet ortamınızı dışa aktardıktan sonra, Controllerı başlatın.

```sh
local-shell-mcp --mode mcp
```

Tek sıralı yayın için, indirdiğiniz yürütülebilir dosyayı kullanın. Kurulan Controller, derlenmiş frontend’i destekler; JavaScript geliştirme aracı ise sadece kaynak kodların derlenmesi için gereklidir. Daha fazla bilgi için [WebUI geliştirme talimatlarına](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) bakınız.

## 2. Tarayıcı çalışma alanını açın

Açık `http://127.0.0.1:8765/ui` Yönetici sunucusundan veya yapılandırılmış HTTPS URL’inden… `/ui`O dağıtım için yapılandırılmış olan LSM kimlik doğrulamasıyla giriş yapın. Uzaktan erişim için kimliği doğrulanmış HTTPS kullanın. Sohbet ve kontrol sayfalarının kaynağı aynıdır.

## 3. Model kanalı ekleyin

Model seçiciyi ve kanal yönetimini açın. Bir API kanalı ekleyin veya desteklenen bir hesabı bağlayın. OpenAI ile uyumlu bir uç nokta için, kanal adını girin, “Chat Completions” seçeneğini seçin, API temel URL’sini ve kimlik bilgilerini girin. Ayrıca modelleri bulabilir veya manuel olarak bir model ID girebilirsiniz. Yapılandırmayı kaydedin ve bir model seçin.

Yerel bir çıkarım hizmeti için, yalnızca tarayıcınızdan ulaşılabilecek bir adres kullanılmalıdır. Örneğin, eğer çıkarım hizmeti Controller’ın ağ adresinde bu adreste dinliyorsa, `http://127.0.0.1:8080/v1` uygun olacaktır. Protokoller, hesap yetkilendirmesi, model keşfi ve bağlam sınırları hakkında daha fazla bilgi için [Channels and models](../chat/channels.md) bölümüne bakınız.

## 4. İlk görevi çalıştırın

Bir sohbet başlatın ve modelin bağlantı durumunu test etmek için basit bir soru sorun. Daha sonra sadece okuma işlemi yapabilecek bir araç kullanmayı deneyin.

```text
Controller çalışma alanının ana klasöründeki dosyaları listleyin.
Lütfen bana hangi makineyi incelediğinizi söyleyin ve sonucu özetleyin.
Lütfen dosyaları değiştirmeyin veya herhangi bir yazma işlemi yapmayın.
```

Gerçek araç sonucunu kontrol edin. Eğer bir araç eksikse, sohbet alanındaki araç seçeneklerini, Ajan ayarlarını ve makine yetkililiklerini kontrol edin. Tekrarlanan görevler için kaydedilmiş bir Ajan kullanın ve onun erişimini açıkça ayarlayın. Daha fazla bilgi için lütfen [Araçlar ve yetkililer](../chat/permissions.md) bölümüne bakın.

![WebUI ile yapılan sohbet örneği](../assets/chat/chat-workspace.png)

Bu rehberde ve sonraki sayfalarda yer alan ekran görüntüleri, bir demo modeli üzerinde çalışan bir Controller’da elde edilmiştir. Bu ekran görüntülerinde herhangi bir üretimle ilgili kimlik bilgileri veya konuşmalar bulunmamaktadır. İngilizce UI etiketleri, seçilen dilden farklı olabilir.

## 5. Çalışma alanını keşfedin

| Bölge/Alan | Bunu ne için kullanabiliriz? |
|---|---|
| Chat ve projeler | Chatları başlatmak ve aramak, projeleri düzenlemek, etiketler ve mesajlar için işaretlemeler yapmak |
| Agents | Yeniden kullanılabilir modeller, talimatlar ve araç yapılandırmaları |
| Hafıza ve Beceriler | Yeniden kullanılabilir bilgileri ve talimatları yönetmek |
| Planlanan sohbetler | Kaydedilmiş bir Ajanı, tekrarlanan bir komutla çalıştırın. |
| Dosyalar ve terminaller | Controller ve İşçi ortamlarını kontrol edin veya bunlar üzerinde işlem yapın. |
| Çalışma sayfası | Desteklenen uzaktan GUI oturumlarını incelemek ve kontrol etmek |
| Oturumlar, işler ve denetimler | Dayanıklı görevleri, yürütme ilerlemesini ve araç aktivitelerini kontrol edin. |
| Makineler ve harici MCP’ler | Çalışanları ve iç içe geçmiş MCP sunucularını yönetin. |

Kontrollerin tam listesi, kurulum şeklinize, hesabınıza ve etkinleştirilen özelliklere bağlıdır. Tarayıcıyı kapatmak, sunucu tarafındaki işlemleri sonlandırmaz; işi durdurmak istediğinizde “dur” kontrolünü kullanın.

## Son adımlar…

Tam iş akışı için [WebUI Chat rehberini](../chat/index.md) okuyun. Üretim ayarları, yedekleme ve hata onarımı için ise [Yönetim ve sorun giderme bölümünü](../chat/administration.md) inceleyin.
