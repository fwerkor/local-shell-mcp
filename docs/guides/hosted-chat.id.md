<!-- i18n-source-sha256: f2dd1c4fffcc9783c739a12868fbcfa0023e0e3a783c8ba929f84107e3959e9a -->
# Obrolan yang Dihosting (opsional)

Obrolan yang Dihosting adalah klien Aplikasi MCP dan obrolan BYOK yang dihosting sendiri dan terintegrasi ke dalam antarmuka manusia LSM. Ini **bukan** mode Sesi Logis: percakapan memiliki identitas independen dan secara opsional dapat melampirkan Sesi Logis LSM yang ada. ChatGPT dan klien eksternal lainnya terus bekerja dengan Sesi dan alat LSM yang sama.

## Aktifkan

Obrolan yang Dihosting dinonaktifkan secara default. Tetapkan:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Mulai ulang Pengontrol dan buka **Obrolan yang Dihosting** tepat di bawah pemilih UI Web/TUI. Fitur ini juga memiliki entri bilah atas seluler. Host obrolan menggunakan identitas dan cakupan LSM OAuth yang ada. Pengontrol yang sama mengoperasikan server MCP yang digunakan oleh loop alat model; Pekerja tidak dapat memulai eksekusi.

## Profil model

Pilih **Profil model** untuk membuat/mengedit profil dengan nama, URL dasar API yang kompatibel dengan HTTPS OpenAI, ID model, dan Kunci API opsional. Beberapa profil dapat hidup berdampingan dan percakapan dapat berganti model.

Profil, percakapan, riwayat pesan lengkap, dan hasil panggilan alat **disimpan di server** melalui backend status LSM yang dikonfigurasi. Cakupannya terikat pada prinsipal yang diautentikasi. Kunci API dienkripsi dengan AES-GCM dan tidak pernah dikembalikan dari daftar profil atau titik akhir detail profil. Itu tidak disimpan di penyimpanan browser, dikirim ke model sebagai perintah, atau disertakan dalam log audit. Host obrolan meneruskannya hanya ke API model yang dipilih.

Penerapan pertama yang didukung file membuat `hosted-chat-encryption-key` di direktori negara bagian dengan mode 0600. **Cadangkan file ini bersama dengan data negara. Tanpanya, Kunci API yang disimpan tidak dapat didekripsi.** Jika Pengontrol menggunakan Redis, beberapa replika, atau backend status non-file lainnya, konfigurasikan kunci URL-safe-base64 32 byte yang stabil dan dibagikan:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

Jangan memutar pengaturan ini tanpa memigrasikan profil terenkripsi. Jangan gunakan penyimpanan status dalam memori saat diperlukan percakapan yang tahan lama.

Secara default, hanya titik akhir model HTTPS dengan nama host DNS yang diterima; titik akhir lokal/pribadi dan HTTP ditolak untuk mengurangi risiko pemalsuan permintaan sisi server. Administrator yang sengaja menghosting gateway model pribadi tepercaya dapat ikut serta:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

Jangan aktifkan ini pada Pengontrol multi-pengguna yang tidak tepercaya kecuali pengguna diizinkan untuk menghubungi layanan internal.

## Percakapan dan Aplikasi MCP

Buat percakapan menggunakan profil model yang disimpan. Setiap giliran yang dikirimkan menjadi tugas latar belakang milik server; menutup browser tidak membatalkan tugas. Panggilan teks dan alat yang telah selesai diperiksa secara tahan lama di antara langkah-langkah model/alat. Berhenti secara eksplisit untuk menyela. Saat Pengontrol dihidupkan ulang, proses yang terhenti akan ditandai seperti itu dan dapat dilanjutkan pada giliran baru, namun **panggilan alat dengan hasil yang tidak diketahui tidak pernah diputar ulang secara otomatis**.

Seluruh riwayat pesan percakapan disimpan di penyimpanan. Hanya jendela terkini yang dibatasi yang dikirim ke model sekaligus untuk mengontrol ukuran konteks. Panggilan alat dikirim melalui titik akhir MCP yang diautentikasi LSM, menjaga semua izin alat biasa dan perilaku audit/preflight.

Buka **Live Workspace** untuk merender sumber daya Aplikasi MCP `workspace_open` LSM yang ada di dalam tampilan tersemat. Host menggunakan jembatan `@modelcontextprotocol/ext-apps` untuk siklus hidup aplikasi, pembaruan kredensial, panggilan alat, dan tindakan antar-agen. Tidak ada pengelola file, terminal, audit, atau UI pekerjaan kedua yang diterapkan.

Opsional terlampir `session_id` memungkinkan Obrolan yang Dihosting menggunakan dan menampilkan Sesi Logis yang ada; itu tidak mengklasifikasi ulang Sesi atau memberikan kepemilikan Obrolan yang Dihosting atas Sesi tersebut. Pengidentifikasi percakapan obrolan dan pengidentifikasi Sesi Logis terpisah.

## Batasan

- Permintaan model menggunakan Penyelesaian Obrolan yang kompatibel dengan OpenAI dengan pemanggilan alat; protokol penyedia lain memerlukan adaptor.
- Pengamanan per putaran membatasi iterasi model dan pemanggilan alat. Tugas yang lebih panjang dapat dilanjutkan pada babak baru dengan menggunakan sejarah yang tahan lama.
- Penghapusan percakapan obrolan bersifat eksplisit. Tidak ada penggusuran riwayat otomatis yang dilakukan.
- Pengontrol harus dapat dijangkau jaringan oleh klien MCP-nya sendiri dan browser harus diberi otorisasi untuk LSM Live Workspace API.
