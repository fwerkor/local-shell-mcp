<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# Kullanıcı arayüzü

`local-shell-mcp`, aynı service API, workspace, persistent terminal registry, remote-worker registry ve MCP audit log üzerinde iki uyumlu human interface sunar:

- **Web UI**, hızlı operasyonel inceleme için optimize edilmiş yerel bir tarayıcı panosudur.
- **OpenTUI**, tam terminal odaklı uygulamadır ve hem tarayıcı içinde hem de yerel terminal komutu olarak kullanılabilir.

Hiçbir mode ayrı bir control plane oluşturmaz. Interface değiştirmek bağlı machine’leri, Sessions, jobs, permission veya audit data’yı değiştirmez.

## Servisi başlatma

`local-shell-mcp`'yi normal şekilde başlatın:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

ChatGPT MCP Apps render ettiğinde `workspace_open(session_id=...)`, **açıkça seçilmiş Logical Session** için yüzen bir ortak çalışma görünümü açar. Kalıcı görev durumu — objective, progress, Plan ve Activity — Session tarafından tutulur; Live Workspace yalnızca bu durumu, canlı etkinliği ve insan kontrollerini gösterir. Görev kimliğini MCP transport üzerinden asla çıkarmaz.

Tipik açık handoff akışı şöyledir:

```text
session_manage(action="start", objective=...)
        -> session_id
... logical_session_id=session_id ile tool çağrıları
... session_manage(action="report", session_id=...) ...
yeni ChatGPT konuşması
kullanıcı önceki session_id değerini iletir
session_manage(action="resume", session_id=...)
        -> mevcut progress, Plan ve yakın Activity
workspace_open(session_id=...)
        -> aynı Session görünümü
```

`session_id` tek kalıcı görev kimliğidir. Agent başka bir konuşmadaki Sessionı listelememeli, tahmin etmemeli veya otomatik seçmemelidir. Çalışmaya yeni bir konuşmada devam etmek için kullanıcı mevcut `session_id` değerini açıkça iletir. Agent start/resume sonrasında, anlamlı ilerleme checkpointlerinde ve turn bitmeden önce aktif `session_id` değerini kullanıcıya bildirmelidir; böylece elle handoff yapılabilir. Sessions machine veya working directory ile bağlı değildir; normal tool parametreleri local/remote targetları ve pathleri seçmeye devam eder.

İsteğe bağlı bir `plan_manage` Planı Session için Goal modeu etkinleştirir. Plan active durumdaysa ve 15 dakika agent activity olmazsa ilişkili Live Workspace ChatGPT’den devam etmesini isteyebilir. Continuation aynı açık `session_id` değerini resume eder ve kabul veya ret durumuna bakılmaksızın 10 denemeyle sınırlıdır. blocked, completed ve cancelled Planlar otomatik devam ettirilmez; tüm steps değerleri completed veya skipped olan active bir Plan, resumed agentın Planı bitirebilmesi için kapanış continuationına uygun kalır. İnsan pause/resume/cancel kontrolleri geçici Live Workspace state yerine Sessionın sahip olduğu Planı günceller.

## Tarayıcı arayüzü

Şunu açın:

```text
http://127.0.0.1:8765/ui
```

Genel kullanıma açık deployment için yapılandırılmış HTTPS origin'i kullanın:

```text
https://your-public-host.example.com/ui
```

Tarayıcı arayüzü MCP ile aynı OAuth sunucusunu ve scope'ları kullanır. Giriş ekranının yüklenebilmesi için sayfa kabuğu ve statik varlıklar herkese açıktır; `/api/ui/*` ve OpenTUI terminal WebSocket'i ise korumalıdır. Erişim token'ları yalnızca tarayıcı session storage'ında tutulur.

### Arayüz seçme

OAuth ekranında iki giriş noktası vardır:

- **Open Web UI**, yetkilendirir ve yerel panoyu açar.
- **Continue to OpenTUI**, yetkilendirir ve önceki tarayıcı davranışını koruyarak terminal arayüzünü açar.

Yetkilendirmeden sonra kenar çubuğundaki arayüz seçici, yeniden giriş gerektirmeden Web UI ve OpenTUI arasında geçiş yapar. OpenTUI'ye geçici geçişte mevcut yerel sayfa hatırlanır.

Rotalar yer imlerine eklenebilir:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` ve `#/dashboard`, Overview takma adlarıdır. `#/tui` ve `#/opentui`, Console takma adlarıdır.

## Yerel Web UI

Yerel Web UI mevcut kullanıcı arayüzü API'sini beş saniyede bir sorgular ve terminal hücreleri yerine tarayıcıya özgü kontrolleri işler. OpenTUI seçilene kadar PTY başlatmaz.

### Overview

Overview en yüksek öncelikli operasyonel bilgileri önce gösterir:

- Controller sağlığı ve geçerli LSM sürümü.
- Çevrimiçi ve çevrimdışı makine sayıları.
- Aktif tracked jobs ve kalıcı terminal oturumları.
- CPU, bellek, workspace diski, load, ağ aktarım hızı ve uptime.
- Worker durumu, kaynak eşikleri, başarısız jobs ve başarısız MCP çağrılarından üretilen uyarılar.
- Model kaynaklı son MCP etkinliği.

### Machines

Machines, yerel controller ve bağlı uzak workers'ı durum, platform, sürüm, çalışma dizini, yetenekler ve last-seen bilgileriyle listeler.

### Workloads

Workloads aktif tracked jobs ile bağımsız kalıcı shell oturumlarını birleştirir. Web UI bu kayıtlar için salt okunurdur; etkileşimli oturum yönetimi için OpenTUI kullanın.

### Activity

Activity mevcut uyarıları son MCP denetim etkinliğiyle birleştirir. İnsan tarafından girilen komutlar ve dosya işlemleri MCP denetim günlüğüne dahil edilmez.

## Tarayıcı OpenTUI

**OpenTUI** seçildiğinde yerel terminal başlatıcısıyla aynı OpenTUI uygulaması gerektiğinde başlatılır. Tarayıcı console şu özellikleri korur:

- WebSocket üzerinden kimliği doğrulanmış ikili PTY aktarımı.
- Otomatik terminal boyutlandırma ve yeniden bağlanma backoff'u.
- OpenTUI kontrolleriyle fare etkileşimi.
- Tam ekran modu ve tarayıcı güvenli klavye kısayolları.
- Mobil kısayol tuşları ve açık yazılım klavyesi kontrolü.
- xterm.js üzerinden SIXEL ve inline image desteği.

Kullanıcı yerel Web UI modunda kaldığı sürece tarayıcı OpenTUI PTY oluşturmaz.

## Yerel OpenTUI

Bağımsız release yürütülebilirleri platform OpenTUI runtime'ını içerir. Ana yürütülebilir dosyayı tutun, servisi başlatın ve ardından çalıştırın:

```bash
local-shell-mcp tui
```

Yerel TUI insan operatörden giriş istemez. Belgelenen Docker Compose kurulumunda launcher, loopback Human UI API için yalnızca host üzerinde tutulan dedicated CLI credentialı yeniden kullanır; diğer split-runtime düzenlerinde `--token-file` kullanılabilir. Tarayıcı tarafından başlatılan OpenTUI örnekleri controller process içinde gerektiğinde oluşturulan ve state directory ya da state backend içine hiç yazılmayan bir credential kullanır. Reverse proxy yalnızca loopback üzerinden bağlandığı için bu yerel bypasslardan hiçbirini kazanmaz.

Bir source checkout da Bun bağımlılıkları kurulduktan sonra TUI'yi çalıştırabilir:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

`--api-base` yalnızca yerel servis varsayılan dışı bir port kullanıyorsa kullanılmalıdır:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## OpenTUI ekranları

### Dashboard

Dashboard, OpenTUI operasyonel görünümüdür. Geniş terminaller node, workload, alert, activity, sistem bilgisi ve trend bölgelerini ayrı gösterir; dar terminaller bunları yatay kaydırma olmadan kompakt özetlere daraltır.

### Files

Files, yerel ve uzak makineler için LSM'ye özgü üç panelli dosya yöneticisidir. Oluşturma, düzenleme, yeniden adlandırma, kopyalama, taşıma, yapıştırma, silme, gizli dosya geçişi, yenileme, metin önizleme, ikili önizleme ve sınırlı resim küçük resimleri sağlar.

### Terminals

Terminals, yerel ve uzak makinelerde kalıcı shell oturumlarını yönetir. Tam komut girişi, raw etkileşimli giriş, oturum değiştirme, oturum oluşturma ve sonlandırma, son çıktı ve daraltılabilir MCP audit rail desteği vardır.

### Audit

Audit sınırlı JSONL denetim günlüğünü okur ve node, operation, event, session, search, time-range ve sort filtreleriyle kayıt ayrıntısı incelemesini destekler.

### Remotes

Remotes çevrimiçi ve çevrimdışı uzak workers, yetenekler, çalışma dizinleri ve sistem metadata'sını gösterir. Tek kullanımlık join invite oluşturabilir, bir node'u yeniden adlandırabilir veya kalıcı identity'sini iptal edebilir.

## OpenTUI gezinmesi

Üst kategori çubuğu ve bağlamsal footer eylemleri hem yerel terminallerde hem de tarayıcı console'da fareyle tıklanabilir.

| Tuşlar | Eylem |
|---|---|
| `Alt+1` … `Alt+5` | Dashboard, Files, Terminals, Remotes veya Audit açar. |
| `F2` … `F6` | Alternatif kategori shortcut’ları. |
| `F1` | Klavye kılavuzunu açar. |
| `F9` | Makine listesini yeniler. |
| `Alt+Q` | Tarayıcıya ayrılmış bir Ctrl kısayolunu tetiklemeden yerel OpenTUI sürecinden çıkar. |

Terminals yeni oturum için `Alt+N`, seçili oturumu sonlandırmak için `Alt+W`, audit rail'i açıp kapatmak için `Alt+A`, yenilemek için `Alt+R` ve oturum değiştirmek için `Alt+Left/Right` kullanır. Tarayıcı console bu kombinasyonları tarayıcı düzeyi gezinme veya menü işleminden önce yakalar.

## Yapılandırma

| YAML anahtarı | Ortam değişkeni | Varsayılan | Amaç |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Kullanıcı arayüzlerini bağlar veya devre dışı bırakır. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | MCP servisindeki tarayıcı arayüzü mount yolu. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Yerel OpenTUI yürütülebilir çözümlemesini geçersiz kılar. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | OpenTUI tarayıcı-console deployment'ları için korunan duvar kâğıdı ayarı. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Etkin olmayan tarayıcı OpenTUI PTY'sini bu saniye sonrasında kapatır; `0` timeout'u kapatır. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Aynı anda açık en fazla tarayıcı OpenTUI PTY oturumu. |

## Paketleme notları

- Docker image'ları Web UI varlıklarını ve yerel OpenTUI runtime'ını içerir.
- Bağımsız yürütülebilirler Web UI varlıklarını ve sıkıştırılmış platform OpenTUI runtime'ını gömer.
- Python wheel'ları tarayıcı varlıklarını içerir; yerel OpenTUI için release yürütülebiliri veya Bun bağımlılıkları kurulmuş source checkout gerekir.
- Her iki arayüz de MCP ile aynı süreç ve porttan sunulur; ek web servisi gerekmez.
