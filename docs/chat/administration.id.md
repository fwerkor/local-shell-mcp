<!-- i18n-source-sha256: 91fa7e8e41354be2761864ffe05d1efb85063953c79a40065ad61661cc15b836 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Pembuatan administrasi dan penanganan masalah yang muncul

## Arsitektur Pengimplementasian

Frontend WebUI disajikan oleh Python Controller, yang berada di lokasi yang sama dengan endpoint REST dan MCPnya. Backend defaultnya adalah SQLite. Binari dan paket-paket yang disertakan dalam distribusi tersebut mencakup aset-aset frontend yang telah dikompilasi. Untuk membuat frontend dari sumber kode sumber, diperlukan alat pembangun JavaScript. Node.js, MongoDB, Meilisearch, serta backend LibreChat yang didistribusikan secara terpisah tidak diperlukan.

Gunakan [Quickstart](../getting-started/quickstart.md) dan [Reference Konfigurasi](../reference/configuration.md) untuk proses pembangunan aplikasi. Untuk pembangunan sumber kode, silakan merujuk pada [Instruksi Pembangunan WebUI](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## Pastikan proses pengimplementasiannya berjalan dengan lancar.

Gunakan proxy atau jalur tuner HTTPS yang dapat dipercaya. Gunakan mekanisme autentikasi yang kuat, serta penggunaan kata sandi yang aman. Pertahankan Controller dalam lingkup kontainer atau VM yang sesuai. Batasi akses masuk, dan lindungi kredensial yang digunakan untuk proses eksekusi. Jangan membiarkan endpoint eksekusi yang tidak autentik tersedia di internet publik.

Proxies harus mendukung proses streaming tanpa perlu menampung data hingga proses tersebut selesai. Proxies juga harus mendukung upgrade ke protokol WebSocket untuk antarmuka-antarmuka yang membutuhkannya. Gunakan waktu timeout yang sesuai untuk permintaan model dan alat-alat tertentu, serta izinkan ukuran file yang dapat diunggah sesuai dengan batas yang ditentukan. Pastikan URL publik yang digunakan konsisten dengan origin browser dan callback OAuth. Jangan memperbaiki kesalahan TLS dengan cara memblokir pemeriksaan sertifikat secara global.

Permintaan-permintaan tersebut berasal dari Controller. Pesan-pesan yang dapat dilihat oleh model, lampiran-lampiran, dan hasil pengolahan data dapat dikirim ke API yang telah ditentukan. Pertimbangkan syarat-syarat penanganan data oleh penyedia layanan sebelum menggunakan konten yang bersifat rahasia. Selain itu, lindungi juga rahasia-rahasia terkait MCP dan token-token yang digunakan oleh Worker.

## Keadaan, cadangan, dan proses pembaruan

Direktori keadaan default adalah `.local-shell-mcp`, yang berada di bawah workspace yang telah dikonfigurasi. `LOCAL_SHELL_MCP_STATE_DIR` dapat digunakan untuk mengubah direktori tersebut. Database yang digunakan bersama-sama adalah `lsm.sqlite3`. Chat, proyek-proyek, pengaturan-pengaturan, Agents, memori, jadwal, dan status eksekusi disimpan di server. Lampiran-lampiran, file-file workspace, dan benda-benda lainnya dapat disimpan di luar database.

Lakukan pembuatan salinan lengkap dari direktori state tersebut. Selain itu, buat juga salinan dari konfigurasi yang ada di luar direktori tersebut, serta file-file yang berkaitan dengan lingkungan pengembangan dan rahasia-rahasia tertentu. Anggaplah proses pembuatan salinan sebagai hal yang sensitif. Pembuatan salinan hanya berupa database saja mungkin akan menghilangkan file-file tambahan atau konfigurasi yang terkait dengannya. Gunakan mekanisme backup yang konsisten, misalnya menggunakan Controller yang sedang dalam keadaan “ quiescent ” atau menggunakan mekanisme backup SQLite yang konsisten. Hanya salinan dari file database utama saja yang perlu dibuat, karena salinan tersebut tidak akan mencakup konten WAL yang telah disimpan. Verifikasi hasil backup dengan cara memulihkannya ke dalam lingkungan pengembangan uji coba yang terisolasi.

Sebelum melakukan pembaruan, catat versi saat ini, jalur eksekusi program, konfigurasi sistem, lokasi data yang digunakan, serta tugas-tugas yang sedang berjalan. Hentikan atau keluarkan data yang terkait dengan proses eksekusi tersebut secara aman. Buatlah salinan cadangan yang konsisten. Lakukan pembaruan pada instalasi yang sama, lalu verifikasi kembali proses autentikasi, catatan percakapan, proses generasi model, streaming, serta tugas-tugas yang ditetapkan secara tertulis. Migrasi data dari versi lama ke versi baru didukung saat proses start-up berlangsung. Simpan file-file lama hingga Anda memastikan bahwa migrasi telah berhasil dilakukan. Jangan mengganti direktori data produksi dengan direktori uji coba yang kosong.

Rollback bukan sekadar mengubah struktur biner dari data basis data yang telah berubah akibat proses migrasi. Perlu dipertahankan kondisi yang seharusnya terjadi sebelum proses migrasi dilakukan. Hindari penggunaan dua controller yang memiliki konfigurasi yang berbeda pada satu storage yang sama.

## Mendiagnosis masalah yang terjadi pada chat.

| Gejala-gejala yang muncul. | Periksa terlebih dahulu. |
|---|---|
| Tidak dapat memuat tampilan UI. | Proses pengendalian konten, bundel antarmuka pengguna, alamat URL yang benar, mekanisme proxy, serta proses autentikasi. |
| Model yang hilang. | Konfigurasi saluran komunikasi, identitas model, otorisasi akun. |
| Keterlambatan atau kesalahan dari pihak penyedia layanan (HTTP 401/403). | Kata kunci API/akun, izin yang dimiliki oleh penyedia layanan, saluran komunikasi yang dipilih, dan protokol yang digunakan. |
| HTTP 429 | Batasan kecepatan/kuota dari pihak penyedia layanan, jumlah permintaan yang terjadi secara bersamaan, status akun/plan yang digunakan. |
| HTTP 400/413/422 | Kompatibilitas permintaan, ukuran input/konteks, batasan pada attachment, parameter model. |
| HTTP 5xx atau timeout. | Kondisi penyedia layanan, jaringan, kapasitas model penyedia layanan, serta batas waktu proxy. |
| Output berhenti ditransmisikan. | Proses konectasi ulang diperlukan; periksa status generasi dan informasi kesalahan yang terjadi. |
| Alat yang digunakan tidak tersedia. | Fitur-fitur seperti kemampuan agen, aturan akses mesin, opsi OAuth, serta pengaturan kontroler. |
| Pekerja yang sedang tidak online/terhubung. | Pendaftaran pekerja, koneksi keluar, log heartbeat, dan log Controller. |
| Masih ada proses persetujuan atau pertanyaan yang perlu ditangani. | Buka percakapan tersebut dan periksa tindakan yang diminta. |
| Jadwal tidak berjalan. | Status yang aktif, zona waktu, agen/channel, target, otorisasi yang telah disimpan, percobaan terakhir. |

Jangan menganggap bahwa semua kesalahan HTTP berasal dari satu layanan yang sama. Perlu dibedakan antara kegagalan login LSM, kesalahan API dari layanan upstream, kesalahan eksternal MCP, dan kesalahan dalam proses transmisi data oleh Worker. Periksa detail kesalahan tersebut, serta log-log yang berkaitan dengan hal tersebut. Hapus informasi seperti kunci pengamanan, token bearer, dan URL callback sebelum membagikannya.

## Proses percobaan dan pemulihan oleh penyedia layanan

Sebelum respons model dimulai, galat koneksi sementara dan galat HTTP tertentu (408, 429, 500, 502, 503, 504) dapat dicoba ulang dengan waktu tunggu terbatas. Jeda percobaan ulang biasa saat ini adalah 1, 2, 4, 8, 16, 30, 30, dan 30 detik (delapan percobaan ulang setelah permintaan awal). HTTP Retry-After dapat memperpanjang jeda hingga 120 detik; galat streaming tertentu menambahkan variasi acak. Batas percobaan ulang berlaku untuk setiap permintaan model, bukan hitungan seumur percakapan. Kompaksi memiliki jalur pemulihannya sendiri. Pembatasan laju akibat kredit habis dapat bertahan hingga penyedia mengisi kuota kembali. Percobaan ulang otomatis tidak menjamin keberhasilan dan tidak membuat langganan tak terbatas.

Interupsi yang terjadi di tengah proses berbeda dengan kesalahan yang terjadi sebelum terjadinya respons pertama. Jangan mengandalkan kembali urutan eksekusi alat tersebut secara otomatis. Periksa riwayat proses yang telah disimpan serta keadaan eksternal sebelum mencoba lagi. Jika proses masih berlangsung, hubungkan kembali sistem tersebut, bukan memulai proses yang sama dari awal. Jika proses berakhir dengan kegagalan, gunakan fitur pemulihan/percobaan yang tersedia, atau mulailah proses baru dengan cara yang sesuai, jika proses asli tidak dapat dilanjutkan.

Kegagalan terkait konteks perlu diselidiki secara terpisah dari kesalahan biasa yang terjadi saat proses pembuatan model. Periksa batas konteks yang efektif, kompatibilitas model, hasil yang terlalu besar, serta kuota yang tersedia. Lihat [Memory and context](context.md).

## Apa yang perlu dimasukkan dalam laporan bug?

Laporkan versi/LKOM LSM, metode instalasi, sistem operasi, model protokol yang digunakan, jenis endpoint yang telah disterilkan, ID model, waktu yang diperkirakan, langkah-langkah untuk mereproduksi masalah tersebut, status chat/run yang relevan, serta rincian kesalahan yang terjadi. Untuk masalah yang berlaku di jarak jauh, tambahkan informasi mengenai versi Worker, nama mesin, serta status heartbeat/poll. Jika memungkinkan, sertakan juga contoh cara mereproduksi masalah tersebut. Jangan mengirimkan kunci API, token OAuth, pesan-pesan pribadi, atau data pribadi lainnya.
