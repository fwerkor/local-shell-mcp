<!-- i18n-source-sha256: 0d50677fe8bd21dbf6f3fff366adea800f15d50fdbc67ed3b77abf84437f73eb -->
# Hubungkan Gemini Task / aplikasi khusus

Fitur **aplikasi terhubung khusus** Gemini memungkinkan pengguna Gemini yang memenuhi syarat menghubungkan server MCP jarak jauh. LSM dapat menyediakan titik akhir MCP. Ini adalah **koneksi klien alternatif** ke [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md), dan klien MCP lainnya; itu tidak menggantikan atau menyebarkan Pengontrol LSM.

Google saat ini membatasi aplikasi khusus untuk **pengguna berusia 18 tahun ke atas di Amerika Serikat**, masuk dengan **Akun Google pribadi** dan **Tetap aktifkan Aktivitas**. Fitur ini tersedia dalam **Bahasa Inggris**. Koneksi harus dibuat di aplikasi web Gemini, meskipun aplikasi yang terhubung nantinya dapat digunakan di perangkat seluler. Ketersediaan dan label UI dapat berubah; konsultasikan dengan [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

## Sebelum menghubungkan

- Mulai runtime LSM, misalnya dengan [Docker Compose](../installation/docker.md), dan verifikasi kesehatannya.
- Ekspos endpoint MCP-nya melalui **HTTPS yang dapat dijangkau secara publik** dan tetap aktifkan OAuth.
- Ketahui detail autentikasi Pengontrol dan setujui hanya cakupan yang Anda perlukan.
- Gunakan ruang kerja atau wadah yang terbatas. Gemini mungkin meminta operasi dengan efek nyata pada file, mesin, dan terminal.

Titik akhir untuk masuk ke Gemini adalah:

```text
https://your-public-host.example.com/mcp
```

Jangan memasukkan UI web (`/ui`), URL LibreChat, atau situs asal tanpa `/mcp`. Penerapan publik tidak boleh menonaktifkan autentikasi untuk mengatasi kesalahan koneksi.

## Terhubung di Gemini

1. Di komputer, buka [Gemini](https://gemini.google.com/) dan masuk dengan akun pribadi yang memenuhi syarat.
2. Buka **Pengaturan & bantuan → Aplikasi Terhubung**. Tergantung pada antarmuka saat ini, mungkin ada di **Kecerdasan Pribadi → Aplikasi Terhubung**.
3. Di bagian **Aplikasi khusus**, pilih **Tambahkan aplikasi khusus** atau gunakan bidang URL aplikasi khusus.
4. Tempelkan URL `/mcp` LSM HTTPS, lalu pilih **Berikutnya**.
5. Selesaikan alur OAuth dan persetujuan dengan Pengontrol LSM. LSM mendukung penemuan OAuth dan pendaftaran klien dinamis. Jika Gemini meminta kredensial klien OAuth manual, periksa opsi lanjutannya dan penyiapan LSM OAuth Anda sebelum melanjutkan.
6. Dalam percakapan Gemini, ketik `@` dan pilih aplikasi khusus yang terhubung untuk meminta alat LSM.

Mulailah dengan: "Gunakan aplikasi LSM yang terhubung untuk memeriksa lingkungan dan membuat daftar file ruang kerja. Jangan mengubah apa pun." Periksa hasil alat dan audit Pengendali sebelum mencoba operasi tulis.

## Gunakan mode Task (sebelumnya Spark)

Untuk pengembangan bertahap, debugging, dan pemeliharaan server, gunakan **Task** alih-alih chat biasa: mode ini memungkinkan perencanaan, penggunaan alat berulang kali, dan pemantauan progres. Ini bukan jaminan kecepatan atau kualitas terukur.

Pada beranda Gemini, pilih **Task** di bawah kotak teks dan selesaikan penyiapan jika diminta. Ketik `@`, pilih LSM jika tersedia, lalu sebutkan tujuan, mesin atau ruang kerja, dan kriteria penyelesaian.

Contoh: “Gunakan LSM untuk memeriksa repositori, mereproduksi tes yang gagal, memperbaiki penyebabnya, dan menjalankan ulang tes. Laporkan berkas yang berubah dan hasilnya.”

Pantau progres dan setujui tindakan yang diperlukan. Periksa panggilan LSM di log audit Controller: komputer cloud Gemini bukan ruang kerja LSM Anda. Pastikan Controller dan Worker yang diperlukan tetap online. Task dan aplikasi khusus memiliki persyaratan akses berbeda; jika opsi tidak ada, lihat [panduan resmi Task](https://support.google.com/gemini/answer/17094507).

## Batasan dan pemecahan masalah

- **Tidak ada opsi Aplikasi khusus:** konfirmasi akun, wilayah, usia, bahasa, dan kelayakan Keep Activity. Ini adalah batasan ketersediaan sisi Gemini, bukan kesalahan konfigurasi LSM.
- **URL ditolak:** gunakan titik akhir `/mcp` HTTPS yang dapat dijangkau secara eksternal; periksa penemuan OAuth dan proksi terbalik Anda.
- **OAuth gagal:** periksa layar otorisasi LSM, pendaftaran klien, URL panggilan balik, dan cakupan yang diberikan. Jangan publikasikan titik akhir MCP yang tidak diautentikasi.
- **Alat hilang atau gagal:** Dukungan alat/skema MCP sisi klien dapat berbeda-beda. Coba panggilan read-only sederhana dan periksa audit dan log LSM; kompatibilitas penuh dengan setiap fitur klien Gemini tidak dijamin.
- **Memutuskan sambungan:** kembali ke **Aplikasi Terhubung** untuk menonaktifkan, memutuskan tautan, atau menghapus LSM jika tidak diperlukan lagi.

[official guide](https://support.google.com/gemini/answer/17209137) Google menjelaskan alur dan ketersediaan Aplikasi Kustom terbaru. Untuk integrasi Gemini berbasis CLI lokal, lihat [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). LSM [ChatGPT connector tutorial](chatgpt-connector.md) tetap tersedia secara independen.
