<!-- i18n-source-sha256: 474398c2065f510156f7fba24967ca8f6600b586ffb1e002416b7a10dc34c3dc -->
# Ruang kerja web terpadu

**Ruang kerja web LSM terpadu** adalah cara yang disarankan untuk menggunakan local-shell-mcp sehari-hari. Ini menggabungkan obrolan AI, riwayat proyek, dan bidang kendali LSM dalam satu antarmuka responsif, berdasarkan antarmuka LibreChat yang dimodifikasi dan dibuat oleh vendor. Anda masih dapat menghubungkan klien MCP eksternal seperti [ChatGPT](chatgpt-connector.md) atau [Gemini](gemini-spark.md).

Ruang kerja **dihosting sendiri dan opsional untuk dipasang**: ini adalah layanan web terpisah, bukan bagian dari gambar Pengontrol minimal, paket Pekerja jarak jauh yang dapat dijalankan secara mandiri atau jarak jauh. Penerapan khusus pengontrol mempertahankan UI browser asli dan OpenTUI.

## Apa yang ada di ruang kerja?

| Daerah | Apa yang bisa Anda lakukan |
|---|---|
| Obrolan dan proyek | Pilih model yang dikonfigurasi, buat percakapan, atur proyek, temukan obrolan sebelumnya, dan arsipkan percakapan. Riwayat tetap ada di server. |
| Ikhtisar pengontrol | Lihat kesehatan, aktivitas terkini, dan mesin yang terhubung. |
| File | Telusuri dan kelola file lokal atau jarak jauh. |
| Terminal | Bekerja dengan terminal persisten pada Pengendali atau Pekerja. |
| Desktop | Periksa dan kendalikan sesi GUI jarak jauh. |
| Sesi | Periksa tugas LSM yang tahan lama dan siklus hidupnya. |
| Remote | Hubungkan dan kelola Pekerja keluar. |
| Audit | Periksa aktivitas alat yang berasal dari model. |
| MCP Bersarang | Daftarkan, edit, aktifkan, nonaktifkan, segarkan, dan hapus server MCP eksternal di belakang LSM. |

Rute Pengontrol adalah `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` dan `/control/audit`. Obrolan dibuka di `/c/new`. Manajer MCP LSM mengontrol **registrasi MCP bertingkat LSM**; itu tidak membuat registri kedua di LibreChat.

## Terapkan tumpukan obrolan opsional

1. [Install and start an LSM Controller](quickstart.md) dengan OAuth, ruang kerja yang diisolasi dengan tepat dan penyimpanan status `file` atau `redis` yang persisten. Instal Docker Compose dan kloning repositori ke host yang menjalankan tumpukan web.
2. Berikan **dua asal HTTPS di situs yang sama**, seperti `https://lsm.example.org` untuk Pengontrol dan `https://chat.example.org` untuk ruang kerja. Layanan obrolan tidak terekspos secara langsung pada jaringan yang tidak tepercaya.
3. Hasilkan satu rahasia jembatan dengan `openssl rand -hex 32`. Konfigurasikan variabel lingkungan berikut pada **Layanan pengontrol**, menggunakan rahasia tersebut, lalu mulai ulang:

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. Di checkout repositori, konfigurasikan tumpukan web opsional. Gunakan file lingkungan pribadi, atau ekspor nilai yang ditunjukkan di bawah ini; hasilkan rahasia kuat yang unik, dan jangan lakukan:

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Render konfigurasi pribadi, lalu buat dan mulai tumpukan obrolan yang diterapkan secara terpisah:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

Saat menggunakan penerapan root Docker Compose, variabel Pengontrol di atas termasuk dalam root `.env` dan diteruskan ke container. Nilai layanan obrolan dapat diberikan melalui ekspor shell atau file lingkungan pribadi. Kontainer Pengontrol harus dapat dijangkau dari kontainer obrolan di `http://local-shell-mcp:8765` di jaringan Docker bernama. Balikkan port proxy `127.0.0.1:3080` ke asal HTTPS obrolan, pertahankan host eksternal, dan ikuti [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) di repositori. Tumpukan web menjalankan Node.js, MongoDB, Meilisearch dan SearXNG; mereka **tidak** termasuk dalam Pekerja. Penerapan terpisah ini tidak dimulai oleh `docker compose up -d` biasa di root repositori.

## Masuk dan gunakan obrolan

1. Buka `https://lsm.example.org/ui`, autentikasi menggunakan login **LSM Controller**, dan ikuti handoff satu kali ke ruang kerja web. Anda tidak membuat akun pengguna LibreChat kedua.
2. Konfigurasikan penyedia LLM atau titik akhir model yang tersedia untuk layanan obrolan. Ruang kerja menyediakan antarmuka obrolan dan jembatan alat; **tidak termasuk model atau kredit API**.
3. Buat percakapan. Pencarian web dan alat LSM diaktifkan secara default, tergantung pada izin Pengontrol. Gunakan kontrol **Web**, **LSM**, **MCP Eksternal**, dan **Memori** per percakapan sesuai kebutuhan.
4. Mulailah dengan permintaan baca-saja: "Periksa status Pengontrol dan daftarkan root ruang kerja. Jangan ubah file."
5. Navigasikan ke **File**, **Terminal**, **Desktop**, **Sessions**, **Remote** atau **Audit** untuk pemeriksaan dan kontrol langsung.

Unggahan obrolan (hingga 32 MiB) disimpan di ruang kerja Pengontrol dan jalur absolutnya diberikan ke model. Unggahan browser tidak memberikan izin file tambahan. Panggilan alat yang menghadap model melewati otorisasi LSM, audit, dan router pekerja jarak jauh.

## MCP eksternal, keamanan dan data

Gunakan sidebar MCP ruang kerja untuk mengelola server MCP eksternal bertumpuk. Ini mendukung server stdio lokal dan server HTTP, termasuk variabel lingkungan pribadi terpisah dan header permintaan. Rahasia tidak dikembalikan ke browser. Tombol obrolan **MCP Eksternal** memungkinkan penelusuran, inspeksi, dan pemanggilan alat yang disarangkan; itu tidak memberikan model `mcp_manage` ketika alat LSM asli dinonaktifkan. Manajemen UI dilindungi oleh otorisasi Pengontrol normal.

Pesan obrolan, proyek, dan arsip disimpan di sisi server di MongoDB tumpukan web; pencarian menggunakan Meilisearch. Pengontrol secara terpisah memiliki izin alat, identitas Pekerja, status sesi, dan audit. Cadangkan kedua penyimpanan data jika Anda perlu menyimpan semua riwayat. Backend obrolan adalah pengguna tunggal dengan login LSM; jangan memaparkan API internal atau databasenya kepada publik.

UI adalah aplikasi tingkat atas, **bukan iframe**. Jika layanan obrolan opsional tidak dikonfigurasi, `/ui` terus melayani WebUI LSM asli. OpenTUI asli dan klien eksternal tetap didukung.

## Pemecahan masalah

- **Pengalihan tetap pada UI asli:** periksa `LOCAL_SHELL_MCP_LIBRECHAT_URL`, backend status Pengontrol yang persisten, dan proxy balik HTTPS tumpukan web.
- **Login atau handoff gagal:** verifikasi rahasia jembatan yang sama persis berukuran 32 byte atau lebih panjang di kedua sisi, cocok dengan asal situs yang sama, HTTPS, dan jam server.
- **Obrolan dimuat tetapi tidak dapat menjawab:** siapkan titik akhir model aktual atau kredensial API dan periksa log penampung obrolan.
- **Alat MCP tidak ada:** verifikasi cakupan Pengontrol dan tombol per percakapan; registri server bersarang terpisah dari database LibreChat MCP.
- **File atau sesi tampak kosong:** verifikasi bahwa obrolan mencapai Pengontrol dan ruang kerja yang benar, dan periksa log autentikasi API-nya.

Untuk detail implementasi dan pembaruan, lihat [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) dan [human interface guide](../guides/human-interface.md).
