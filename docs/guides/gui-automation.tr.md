<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# Masaüstü GUI otomasyonu

`local-shell-mcp` Linux, Windows ve macOS üzerindeki yerel masaüstü uygulamalarını gözlemleyebilir ve kontrol edebilir. Genel arayüz bilerek küçük tutulur:

| Araç | Amaç |
|---|---|
| `gui_list` | Görünür uygulama pencerelerini listeler ve etkin yerel backend ile yeteneklerini bildirir. |
| `gui_state` | Bir pencereyi gözlemler. Kısa ömürlü bir `state_id`, erişilebilirlik öğeleri, pencere geometrisi ve isteğe bağlı yerel MCP ekran görüntüsü döndürür. |
| `gui_action` | Tam olarak bu gözleme karşı semantik veya koordinat tabanlı eylemler yürütür. |

Üç araç da isteğe bağlı `machine` parametresini kabul eder; böylece aynı akış bağlı bir masaüstü worker üzerinde kullanılabilir.

## Önce gözlemle, sonra eyleme geç

`gui_list` ile başlayın, bir `window_id` seçin ve ardından `gui_state` çağırın. Dönen erişilebilirlik `element_id` hedef denetimi temsil ediyorsa öncelikle onu kullanın:

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Pencereye göre `x`/`y` koordinatlarını yalnızca arayüz canvas veya özel çizilmiş denetim gibi kullanışlı bir erişilebilirlik öğesi sunmadığında kullanın. Dönen öğe sınırları ve ekran görüntüleri HiDPI/Retina dahil aynı pencere-göreli mantıksal piksel alanını kullanır. Seçili pencerenin dışındaki ham koordinatlar reddedilir.

Bir `state_id` 30 saniye sonra sona erer ve tek kullanımlıktır. Koordinat eylemleri ayrıca hedef pencerenin gözlemden sonra taşınmadığını veya yeniden boyutlandırılmadığını doğrular. Kontrollerden biri başarısız olursa eski koordinatları yeniden kullanmak yerine `gui_state` çağırın.

Desteklenen eylemler `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus` ve `wait`'tir.

## Native WebUI'de insan kontrolü

Native WebUI aynı yerel GUI backendlerini doğrudan insan kontrolü için kullanan bir **Desktop** sayfası içerir. Bir makine ve pencere seçin; canlı pencere görüntüsünde tıklama, çift tıklama, sağ tıklama, sürükleme, tekerlek, klavye kısayolları veya IME/CJK metin alanını kullanın.

Bu yol modelin `state_id` semantiğinden bilerek ayrıdır. Gösterilen her frame gözlenen pencere geometrisini taşır; her insan girdisi isteği, girdi enjekte edilmeden önce pencerenin hâlâ tam olarak bu geometriye sahip olduğunu doğrular. Pencere taşınmış, yeniden boyutlandırılmış veya kaybolmuşsa eylem reddedilir ve WebUI gözlemi yeniler. Ham koordinatlar seçili pencereyle sınırlı kalır.

Klavye ve metin eylemleri enjeksiyondan önce seçili yerel pencereye açıkça odaklanır. WebUI VNC/WebRTC video akışı yerine hafif ekran görüntüsü polling kullanır; yalnızca uzak `gui_human_action` RPC'si controller-worker arasında iç işlemdir ve modellere açık bir MCP aracı değildir.

## Yerel backendler

| Platform | Erişilebilirlik / semantik kontrol | Yakalama ve ham girdi |
|---|---|---|
| Windows | Microsoft UI Automation | Pencere yakalama ve yerel Windows fare/klavye girdisi |
| macOS | Accessibility (`AXUIElement`) | Seçili pencere için `screencapture` ve Quartz `CGEvent` girdisi |
| Linux | AT-SPI | X11 yerel girdi/yakalama; Wayland yerel masaüstü yakalama ve XDG Desktop Portal RemoteDesktop/ScreenCast kullanır |

Mümkün olduğunda önce semantik eylemler denenir. Böylece yerel invoke/press eylemi olan bir düğme piksel koordinatı tahmin edilmeden etkinleştirilebilir. Görsel koordinatlar erişilemeyen veya özel çizilmiş içerik için fallback olarak kalır.

## Platform kurulumu

### Windows

LSM'yi kontrol edeceği uygulamalarla aynı etkileşimli masaüstü oturumunda çalıştırın. Temel `local-shell-mcp` kurulumu headless güvenli kalır ve Windows UI Automation adapterını zorunlu kılmaz; yerel Windows GUI kontrolü gerektiğinde isteğe bağlı `local-shell-mcp[gui]` extra'sını kurun.

### macOS

LSM host sürecine şu izinleri verin:

- semantik kontrol ve girdi için **Erişilebilirlik** izni;
- ekran görüntüleri için **Ekran Kaydı** izni.

Temel paket PyObjC gerektirmez. Yerel macOS GUI kontrolü gerektiğinde isteğe bağlı `local-shell-mcp[gui]` extra'sını kurun; GUI araçlarını hiç kullanmayan makineler bu frameworklere ihtiyaç duymaz.

### Linux

Masaüstü oturumu AT-SPI sunmalıdır. Debian/Ubuntu sistemlerinde gerekli sistem bindingleri normalde şu komutla kurulur:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

Temel paket Python X11 veya D-Bus adapterlarını zorunlu kılmaz. İsteğe bağlı `local-shell-mcp[gui]` extra'sı bunları yerel GUI kullanımı için kurar. Uzak workerlar GUI bağımlılık bootstrapından önce etkin Linux oturumunu algılar: X11 yalnızca X11 adapterına, Wayland yalnızca D-Bus adapterına ihtiyaç duyar; headless worker ikisini de kurmaz. Wayland'de ham işaretçi/klavye fallback'i XDG Desktop Portal RemoteDesktop API'sini kullanır, bu nedenle masaüstü bir kerelik izin/oturum seçici gösterebilir. KDE ve GNOME portal uygulamaları desteklenir. Pencere ekran görüntüleri mevcut yerel yakalama yolunu kullanır ve gerektiğinde Screenshot portalına düşer.

LSM workerları sıklıkla grafik login ortamı dışında başlar. Linux backend doğrudan miras alınmadığında `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE` ve ilgili değişkenleri kullanıcı systemd ortamından geri kazanır.

## Uzak masaüstleri

GUI araçları controller üzerinde değil seçili makinede çalışır. Uzak worker hedef masaüstünün sahibi olan kullanıcı/oturuma ait olmalıdır. GUI adapterları lazy ve GUI çağrılarına özeldir: normal worker başlangıcı ile shell/files/browser kullanımı bunları kurmaz veya import etmez. Linux'ta headless worker herhangi bir GUI pip bootstrapından önce GUI kullanılamıyor yanıtı verir; grafik worker yalnızca etkin X11 veya Wayland oturumunun gerektirdiği adapterı kontrol eder veya kurar.

Uzak `gui_state` tarafından döndürülen ekran görüntüleri LSM dosya aktarım yolu üzerinden taşınır ve modele yerel MCP görüntü içeriği olarak sunulur; worker JSON yanıtına gömülmez.
