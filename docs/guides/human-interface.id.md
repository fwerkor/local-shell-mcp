<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# Antarmuka pengguna

`local-shell-mcp` menyediakan dua human interface yang kompatibel di atas service API, workspace, persistent terminal registry, remote-worker registry, dan MCP audit log yang sama:

- **Web UI** adalah dasbor browser native yang dioptimalkan untuk inspeksi operasional cepat.
- **OpenTUI** adalah aplikasi berorientasi terminal lengkap dan tetap tersedia di browser maupun sebagai perintah terminal native.

Tidak ada mode yang membuat control plane terpisah. Berpindah interface tidak mengubah machine terhubung, Sessions, jobs, permission, atau audit data.

## Memulai layanan

Jalankan `local-shell-mcp` seperti biasa:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

Saat ChatGPT merender MCP Apps, `workspace_open(session_id=...)` membuka tampilan kolaboratif mengambang untuk **Logical Session yang dipilih secara eksplisit**. Session menyimpan state task yang durable—objective, progress, Plan, dan Activity—sementara Live Workspace hanya menampilkan state tersebut, aktivitas live, dan kontrol manusia. Identitas task tidak pernah disimpulkan dari transport MCP.

Handoff eksplisit yang umum adalah:

```text
session_manage(action="start", objective=...)
        -> session_id
... pemanggilan tool dengan logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
percakapan ChatGPT baru
pengguna memberikan session_id sebelumnya
session_manage(action="resume", session_id=...)
        -> progress, Plan, dan Activity terbaru yang sudah ada
workspace_open(session_id=...)
        -> tampilan Session yang sama
```

`session_id` adalah satu-satunya identitas task yang durable. Agent tidak boleh membuat daftar, menyimpulkan, atau otomatis memilih Session dari percakapan lain. Untuk melanjutkan pekerjaan di percakapan baru, pengguna memberikan `session_id` yang sudah ada secara eksplisit. Agent harus menyebutkan `session_id` aktif setelah start/resume, pada checkpoint progres yang bermakna, dan sebelum mengakhiri turn agar handoff manual dapat dilakukan. Session tidak terikat pada machine atau working directory; parameter tool biasa tetap memilih target local/remote dan path.

Plan `plan_manage` opsional mengaktifkan Goal mode untuk Session. Jika Plan active dan tidak ada agent activity selama 15 menit, Live Workspace yang terkait dapat meminta ChatGPT melanjutkan. Continuation me-resume `session_id` eksplisit yang sama dan dibatasi 10 percobaan, baik diterima maupun ditolak. Plan blocked, completed, dan cancelled tidak dilanjutkan otomatis; Plan active dengan semua steps completed atau skipped tetap memenuhi syarat untuk continuation penutup agar agent yang di-resume dapat menyelesaikan Plan. Kontrol manusia pause/resume/cancel memperbarui Plan milik Session, bukan state Live Workspace yang sementara.

## Antarmuka browser

Buka:

```text
http://127.0.0.1:8765/ui
```

Untuk deployment publik, gunakan origin HTTPS yang dikonfigurasi:

```text
https://your-public-host.example.com/ui
```

Antarmuka browser memakai server OAuth dan scope yang sama dengan MCP. Shell halaman dan aset statis bersifat publik agar layar login dapat dimuat, sedangkan `/api/ui/*` dan WebSocket terminal OpenTUI tetap dilindungi. Token akses hanya disimpan dalam session storage browser.

### Memilih antarmuka

Layar OAuth menyediakan dua pintu masuk:

- **Open Web UI** memberi otorisasi dan membuka dasbor native.
- **Continue to OpenTUI** memberi otorisasi dan membuka antarmuka terminal sambil mempertahankan perilaku browser sebelumnya.

Setelah otorisasi, pemilih di sidebar dapat berpindah antara Web UI dan OpenTUI tanpa login ulang. Halaman native saat ini diingat ketika sementara berpindah ke OpenTUI.

Route dapat dibookmark:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` dan `#/dashboard` adalah alias Overview. `#/tui` dan `#/opentui` adalah alias Console.

## Web UI native

Web UI native melakukan polling API antarmuka pengguna yang ada setiap lima detik dan merender kontrol native browser alih-alih sel terminal. PTY tidak dimulai sampai OpenTUI dipilih.

### Overview

Overview menampilkan informasi operasional berprioritas tertinggi terlebih dahulu:

- Kesehatan controller dan versi LSM saat ini.
- Jumlah mesin online dan offline.
- Tracked job aktif dan sesi terminal persisten.
- CPU, memori, disk workspace, load, throughput jaringan, dan uptime.
- Peringatan yang dihasilkan dari status worker, ambang sumber daya, job gagal, dan panggilan MCP gagal.
- Aktivitas MCP terbaru yang berasal dari model.

### Machines

Machines mencantumkan controller lokal dan worker jarak jauh yang terhubung beserta status, platform, versi, direktori kerja, kemampuan, dan informasi last-seen.

### Workloads

Workloads menggabungkan tracked job aktif dan sesi shell persisten mandiri. Web UI tetap read-only untuk record ini; gunakan OpenTUI untuk pengelolaan sesi interaktif.

### Activity

Activity menggabungkan peringatan saat ini dengan aktivitas audit MCP terbaru. Perintah dan operasi file yang dimasukkan manusia tidak masuk ke log audit MCP.

## OpenTUI di browser

Memilih **OpenTUI** memulai secara lazy aplikasi OpenTUI yang sama dengan launcher terminal native. Console browser mempertahankan:

- Transport PTY biner terautentikasi melalui WebSocket.
- Resize terminal otomatis dan backoff reconnect.
- Interaksi mouse dengan kontrol OpenTUI.
- Mode fullscreen dan shortcut keyboard yang aman untuk browser.
- Tombol shortcut mobile dan kontrol keyboard lunak eksplisit.
- Dukungan SIXEL dan inline image melalui xterm.js.

Browser tidak membuat PTY OpenTUI selama pengguna tetap berada dalam mode Web UI native.

## OpenTUI native

Executable release mandiri menyematkan runtime OpenTUI platform. Simpan hanya executable utama, mulai layanan, lalu jalankan:

```bash
local-shell-mcp tui
```

TUI native tidak meminta operator manusia untuk login. Pada setup Docker Compose yang didokumentasikan, launcher memakai kembali dedicated CLI credential yang hanya berada di host untuk Human UI API melalui loopback; layout split-runtime lain dapat memakai `--token-file`. Instance OpenTUI yang dibuat dari browser menggunakan credential di dalam process controller yang dibuat secara lazy dan tidak pernah disimpan ke state directory atau state backend. Reverse proxy tidak memperoleh bypass lokal ini hanya karena terhubung melalui loopback.

Checkout source juga dapat menjalankan TUI setelah memasang dependency Bun:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

Gunakan `--api-base` hanya saat layanan lokal memakai port non-default:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## Layar OpenTUI

### Dashboard

Dashboard adalah ringkasan operasional OpenTUI. Terminal lebar menampilkan region terpisah untuk node, workload, alert, activity, informasi sistem, dan tren; terminal yang lebih sempit melipatnya menjadi ringkasan ringkas tanpa scroll horizontal.

### Files

Files adalah file manager tiga panel native LSM untuk mesin lokal dan jarak jauh. Fitur mencakup buat, edit, rename, copy, move, paste, delete, toggle file tersembunyi, refresh, preview teks, preview biner, dan thumbnail gambar terbatas.

### Terminals

Terminals mengelola sesi shell persisten pada mesin lokal dan jarak jauh. Mendukung input perintah lengkap, input interaktif raw, pergantian sesi, pembuatan dan penghentian sesi, output terbaru, dan rail audit MCP yang dapat dilipat.

### Audit

Audit membaca log audit JSONL terbatas dan mendukung filter node, operation, event, session, search, time-range, dan sort serta inspeksi detail record.

### Remotes

Remotes menampilkan worker jarak jauh online dan offline, kemampuan, direktori kerja, dan metadata sistem. Dapat membuat join invite sekali pakai, mengganti nama node, atau mencabut identity persistennya.

## Navigasi OpenTUI

Bar kategori atas dan aksi footer kontekstual dapat diklik dengan mouse baik di terminal native maupun console browser.

| Tombol | Aksi |
|---|---|
| `Alt+1` … `Alt+5` | Buka Dashboard, Files, Terminals, Remotes, atau Audit. |
| `F2` … `F6` | Shortcut kategori alternatif. |
| `F1` | Buka panduan keyboard. |
| `F9` | Refresh daftar mesin. |
| `Alt+Q` | Keluar dari proses OpenTUI native tanpa memicu shortcut Ctrl yang dicadangkan browser. |

Terminals memakai `Alt+N` untuk sesi baru, `Alt+W` untuk menghentikan sesi terpilih, `Alt+A` untuk toggle rail audit, `Alt+R` untuk refresh, dan `Alt+Left/Right` untuk berpindah sesi. Console browser menangkap chord ini sebelum navigasi atau pemrosesan menu browser.

## Konfigurasi

| Kunci YAML | Variabel lingkungan | Default | Tujuan |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Mount atau nonaktifkan antarmuka pengguna. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | Path mount antarmuka browser pada layanan MCP. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Override resolusi executable OpenTUI native. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | Pengaturan wallpaper untuk deployment console OpenTUI browser. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Tutup PTY OpenTUI browser yang idle setelah jumlah detik ini; `0` menonaktifkan timeout. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Maksimum sesi PTY OpenTUI browser bersamaan. |

## Catatan packaging

- Image Docker menyertakan aset Web UI dan runtime OpenTUI native.
- Executable mandiri menyematkan aset Web UI dan runtime OpenTUI platform terkompresi.
- Wheel Python menyertakan aset browser; OpenTUI native memerlukan executable release atau checkout source dengan dependency Bun terpasang.
- Kedua antarmuka disajikan dari proses dan port yang sama dengan MCP; tidak diperlukan layanan web tambahan.
