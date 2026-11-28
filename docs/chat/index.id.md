<!-- i18n-source-sha256: 8ec601aa8e9c57afef769d8346567626355ccf88e122e3296735b7af3639c562 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat

LSM WebUI Chat merupakan ruang kerja agen AI yang dibangun sendiri oleh pengguna. Ruang kerja ini terintegrasi ke dalam sistem Controller. Pengguna dapat menggunakan endpoint model mereka sendiri, atau akun yang didukung oleh sistem tersebut. Model tersebut juga dapat mengakses alat-alat dan mesin-mesin milik pengguna. Tidak diperlukan klien MCP eksternal untuk melakukan hal ini. Klien eksternal tetap dapat terhubung ke Controller yang sama secara mandiri.

## Bagaimana bagian-bagian tersebut dapat disatukan satu sama lain?

- **Controller**: Layanan Python yang berfungsi untuk menangani permintaan yang masuk ke aplikasi browser, mengelola eksekusi perintah, serta menyimpan informasi tentang status sistem secara permanen.
- **Kanal:** Ini merupakan koneksi melalui API model tertentu, atau akun yang didukung untuk proses otorisasi. Kanal ini memiliki kredensialnya sendiri, protokolnya sendiri, daftar modelnya sendiri, serta pengaturan-pengaturannya sendiri.
- **Model:** Identifikasi model yang digunakan dalam suatu saluran komunikasi. Identifikasi yang sama pada dua saluran komunikasi tidak berarti bahwa kedua saluran tersebut memiliki endpoint yang sama.
- **Agen:** Sebuah konfigurasi yang dapat digunakan kembali, yang mencakup model, instruksi, alat-alat, keterampilan, dan izin-izinannya.
- **Percakapan:** Pesan-pesan yang telah disimpan, pengaturan-pengaturan yang ada, riwayat eksekusi, serta hubungan antara model/agen dengan pesan-pesan tersebut.
- **Proyek:** Sekelompok percakapan yang memiliki aturan-aturan bersama.
- **Worker**: merupakan target eksekusi yang terhubung ke luar. Ini bukanlah penyedia model, maupun server chat yang terpisah.
- **Logical Session**: Identitas tugas yang dilakukan oleh alat tersebut, yang berbeda dari ID percakapan. Sebuah chat dapat menggunakan identitas ini untuk melacak tujuan, perkembangan proses, dan hasil pekerjaan yang dilakukan oleh alat tersebut.

Model API menerima konteks yang dapat dilihat oleh model, serta hasil dari penggunaan alat-alat yang digunakan. Controller melakukan eksekusi alat-alat yang diizinkan; model tidak terhubung secara langsung ke Worker, maupun mendapatkan kunci model API Anda. Browserlah yang menampilkan percakapan tersebut, dan mengendalikan perilaku Controller.

## Pilih seorang pemandu yang cocok untuk Anda.

| Saya ingin… | Baca |
|---|---|
| Instalasi, login, dan menjalankan tugas pertama. | [Pendekatan cepat](../getting-started/web-workspace.md) |
| Mengonnect model API atau akun yang digunakan. | [Kanal dan model](channels.md) |
| Membuat agen yang dapat digunakan berulang kali, serta membagikan tugas kepada agen tersebut. | [Agen dan keterampilan](agents.md) |
| Mengelola chat, file, dan proyek. | [Konversasi](conversations.md) |
| Memahami cara mengakses data masa lalu serta anggaran yang terkait dengan konteks tertentu. | [Memori dan konteks](context.md) |
| Membatasi eksekusi dan mengelola alat-alat MCP dengan baik. | [Alat dan izin](permissions.md) |
| Jalankan tugas-tugas dan jadwal yang berlangsung lama. | [Tujuan dan automasi](automation.md) |
| Cari informasi di internet dan membaca dokumen-dokumen yang ada. | [Pencarian di jaringan](../guides/webui-network-search.md) |
| Mengoperasikan, membuat cadangan, dan memperbaiki proses deployment. | [Administrasi dan penyelesaian masalah](administration.md) |

## Prinsip-prinsip dasar.

Mulailah dengan permintaan yang bersifat terbatas, hanya untuk membaca informasi saja. Periksa hasil output alat tersebut sebelum melakukan modifikasi apa pun. Model yang digunakan mungkin salah, meskipun alat tersebut berhasil. Kredensial, penyimpanan data, akses ke mesin, dan persetujuan alat merupakan hal-hal yang perlu diperhatikan secara terpisah. Mengubah satu aspek saja tidak otomatis membuat aspek lain juga dapat diubah. Terutama, endpoint chat publik harus dilindungi sebagai bagian dari sistem kontrol remote.

Untuk rute klien MCP eksternal, lihat [Konektivitas klien](../clients/connectivity.md). Untuk argumen-algaran alat yang digunakan, lihat [Referensi alat](../reference/tools.md).
