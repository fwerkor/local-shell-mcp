<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# Otomatisasi GUI desktop

`local-shell-mcp` dapat mengamati dan mengontrol aplikasi desktop asli di Linux, Windows, dan macOS. Permukaan publik sengaja dibuat kecil:

| Alat | Tujuan |
|---|---|
| `gui_list` | Buat daftar jendela aplikasi yang terlihat dan laporkan backend/kemampuan asli yang aktif. |
| `gui_state` | Amati satu jendela. Mengembalikan `state_id` yang berumur pendek, elemen aksesibilitas, geometri jendela, dan opsional tangkapan layar MCP asli. |
| `gui_action` | Jalankan tindakan semantik atau koordinasikan terhadap pengamatan yang tepat tersebut. |

Ketiga alat tersebut menerima `machine` opsional, sehingga alur kerja yang sama dapat menargetkan pekerja desktop yang terhubung.

## Amati, lalu bertindak

Mulailah dengan `gui_list`, pilih `window_id`, lalu panggil `gui_state`. Lebih suka `element_id` aksesibilitas yang dikembalikan setiap kali ada yang mewakili kontrol target:

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Gunakan koordinat `x`/`y` relatif jendela hanya jika UI tidak memiliki elemen aksesibilitas yang berguna, seperti kanvas atau kontrol yang dibuat khusus. Batasan elemen dan tangkapan layar yang dikembalikan menggunakan ruang piksel logis relatif jendela yang sama, termasuk desktop HiDPI/Retina. Koordinat mentah di luar jendela yang dipilih ditolak.

`state_id` kedaluwarsa setelah 30 detik dan hanya sekali pakai. Tindakan koordinat juga memverifikasi bahwa jendela target belum dipindahkan atau diubah ukurannya sejak observasi. Jika salah satu pemeriksaan gagal, panggil lagi `gui_state` alih-alih menggunakan kembali koordinat lama.

Tindakan yang didukung adalah `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus`, dan `wait`.

## Kontrol manusia di WebUI Asli

WebUI Asli memiliki halaman **Desktop** untuk kontrol manusia langsung terhadap backend GUI asli yang sama. Pilih mesin dan jendela, lalu berinteraksi dengan gambar jendela langsung menggunakan klik, klik dua kali, klik kanan, seret, roda, pintasan keyboard, atau bidang teks untuk input IME/CJK.

Jalur ini sengaja dipisahkan dari semantik model `state_id`. Setiap bingkai yang ditampilkan membawa geometri jendela yang diamati; setiap permintaan masukan manusia memvalidasi bahwa jendela masih memiliki geometri yang persis sama sebelum memasukkan masukan. Jika jendela dipindahkan, diubah ukurannya, atau dihilangkan, tindakan akan ditolak dan WebUI menyegarkan pengamatan. Koordinat mentah tetap terikat pada jendela yang dipilih.

Tindakan keyboard dan teks secara eksplisit memfokuskan jendela asli yang dipilih sebelum injeksi. WebUI menggunakan polling tangkapan layar yang ringan dibandingkan streaming video VNC/WebRTC, dan `gui_human_action` RPC yang hanya digunakan dari jarak jauh merupakan operasi pengontrol-ke-pekerja internal, bukan alat MCP yang diekspos ke model.

## Backend asli

| Platform | Aksesibilitas/kontrol semantik | Tangkap dan masukan mentah |
|---|---|---|
| jendela | Otomatisasi UI Microsoft | Pengambilan UIA/jendela ditambah input mouse dan keyboard Windows asli |
| macOS | Aksesibilitas (`AXUIElement`) | `screencapture` untuk jendela yang dipilih ditambah input Quartz `CGEvent` |
| Linux | AT-SPI | masukan/pengambilan asli X11; Wayland menggunakan tangkapan desktop asli dan XDG Desktop Portal RemoteDesktop/ScreenCast untuk input mentah |

Tindakan semantik dicoba terlebih dahulu jika memungkinkan. Oleh karena itu, tombol dengan tindakan pemanggilan/tekan asli dapat diaktifkan tanpa menebak koordinat piksel. Koordinat visual tetap menjadi cadangan untuk konten yang tidak dapat diakses atau dibuat khusus.

## Pengaturan platform

### jendela

Jalankan LSM dalam sesi desktop interaktif yang sama dengan aplikasi yang harus dikontrolnya. Penginstalan dasar `local-shell-mcp` tetap aman tanpa kepala dan tidak memerlukan adaptor Otomatisasi UI Windows; instal tambahan `local-shell-mcp[gui]` opsional ketika kontrol GUI Windows lokal diperlukan.

### macOS

Berikan proses host LSM:

- Izin **Aksesibilitas** untuk kontrol dan masukan semantik.
- Izin **Perekaman Layar** untuk tangkapan layar.

Paket dasar tidak memerlukan PyObjC. Instal tambahan `local-shell-mcp[gui]` opsional ketika kontrol GUI macOS lokal diperlukan; mesin yang tidak pernah menggunakan alat GUI tidak memerlukan kerangka kerja ini.

### Linux

Sesi desktop harus mengekspos AT-SPI. Sistem Debian/Ubuntu biasanya menyediakan pengikatan sistem yang diperlukan dengan:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

Paket dasar tidak memerlukan adaptor Python X11 atau D-Bus. Ekstra `local-shell-mcp[gui]` opsional menginstalnya untuk penggunaan GUI lokal. Pekerja jarak jauh mendeteksi sesi Linux aktif sebelum bootstrap ketergantungan GUI: X11 hanya memerlukan adaptor X11, Wayland hanya memerlukan adaptor D-Bus, dan pekerja tanpa kepala tidak menginstal keduanya. Di Wayland, fallback penunjuk/keyboard mentah menggunakan XDG Desktop Portal RemoteDesktop API, sehingga desktop mungkin menampilkan pemilih izin/sesi satu kali. Implementasi portal KDE dan GNOME didukung. Tangkapan layar jendela menggunakan jalur pengambilan desktop asli yang tersedia dan kembali ke portal Tangkapan Layar bila diperlukan.

Pekerja LSM biasanya memulai di luar lingkungan login grafis. Backend Linux memulihkan `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE`, dan variabel terkait dari lingkungan systemd pengguna ketika variabel tersebut tidak diwarisi secara langsung.

## Desktop jarak jauh

Alat GUI berjalan di mesin yang dipilih, bukan di pengontrol. Pekerja jarak jauh harus milik pengguna/sesi yang memiliki desktop target. Adaptor GUI malas dan terbatas pada panggilan GUI: startup pekerja normal dan penggunaan shell/file/browser tidak menginstal atau mengimpornya. Di Linux, pekerja tanpa kepala mengembalikan GUI yang tidak tersedia sebelum bootstrap pip GUI; pekerja grafis hanya memeriksa atau menginstal adaptor yang diperlukan oleh sesi X11 atau Wayland yang aktif.

Tangkapan layar yang dikembalikan oleh `gui_state` jarak jauh ditransfer melalui jalur transfer file LSM dan diekspos ke model sebagai konten gambar MCP asli; mereka tidak tertanam dalam respons JSON pekerja.
