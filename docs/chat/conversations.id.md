<!-- i18n-source-sha256: 012f0d9f7b350fcf47e3fd6afdf2fc9e7044ff28cb2eca7c029c3d6af35f3b04 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Percakapan dan proyek-proyek

## Buat dan lanjutkan percakapan.

Buka percakapan baru, pilih saluran/agen yang akan digunakan, lalu masukkan pesan yang ingin disampaikan. Chat tersebut berjalan di atas Controller, dan informasi terkini ditampilkan di browser. Mengganti halaman atau menutup tab tidak sama dengan membatalkan proses eksekusi tersebut. Gunakan tombol “Stop” untuk menghentikan proses eksekusi, lalu periksa status hasilnya sebelum memulai operasi lainnya.

Chat yang telah disimpan tetap mempertahankan asosiasi antara model/agen yang digunakan untuk mengelola chat tersebut. Anda dapat mengganti model yang digunakan jika diinginkan. Percakapan yang terjadi dalam chat bukanlah bagian dari sesi logis; percakapan ini hanya menyimpan pesan-pesan pengguna dan model yang digunakan untuk mengelola percakapan tersebut. Sedangkan sesi logis mencakup tujuan pekerjaan, perkembangan proses, dan rencana yang digunakan dalam sesi tersebut. Pastikan untuk mempertahankan ID yang relevan saat menyerahkan tugas yang panjang kepada orang lain.

## Organisasi dan pencarian pekerjaan yang tepat.

Gunakan proyek untuk mengelompokkan percakapan-percakapan yang saling terkait, serta menetapkan aturan izin penggunaan mesin yang berlaku secara umum. Sebuah proyek dapat berisi beberapa chat yang terpisah. Pindahkan atau buat chat-chat tersebut ke proyek yang sesuai, daripada mengasumsikan bahwa percakapan-percakapan tersebut memiliki konteks yang sama. Proyek yang aktif dapat memberikan informasi kepada Agent mengenai organisasi percakapan-percakapan tersebut.

Tag menurutkan percakapan-percakapan tersebut. Tanda-tanda penunjuk pesan menunjuk pada pesan-pesan tertentu, sehingga memungkinkan pengguna untuk kembali ke hasil-hasil yang berguna. Hal ini berbeda dengan cara menandai percakapan secara khusus. Gunakan judul-chat, fitur pencarian, serta indikator “tidak dibaca” untuk menjaga tampilan sidebar agar tetap mudah dikelola.

Proses arsipisasi berarti memindahkan percakapan tersebut dari daftar normal, tanpa menghapus riwayat percakapan yang telah disimpan. Percakapan tersebut dapat dipulihkan kembali melalui antarmuka arsip jika diperlukan. Menghapus sebuah percakapan merupakan tindakan yang merusak data tersebut; jangan gunakan metode penghapusan sebagai pengganti proses arsipisasi. Implementasi saat ini menggunakan format status percakapan yang disimpan dalam SQLite. Jangan mengasumsikan bahwa format arsip Hosted Chat yang lama masih digunakan.

## Operasi pesan dan pelaksanaan tugas-tugas tertentu

Kontrol yang dapat digunakan pada pesan-pesan tersebut bergantung pada jenis pesan dan status eksekusi pesan tersebut saat ini. Anda dapat mengedit atau mencoba lagi proses eksekusi pesan tersebut jika diperlukan. Selain itu, Anda juga dapat menghapus pesan yang telah dipilih, jika pesan tersebut tidak lagi diperlukan. Penggunaan fitur penghapusan ini akan mengubah riwayat percakapan yang telah disimpan, dan hal ini mungkin mempengaruhi konteks selanjutnya. Fitur ini tidak dapat membatalkan perintah shell, penulisan data dari jarak jauh, push data ke Git, atau efek samping lainnya.

Ketika mencoba kembali melakukan proses yang gagal, bacalah informasi mengenai kesalahan yang terjadi secara rinci, dan periksa terlebih dahulu apakah langkah-langkah yang telah dilakukan sudah selesai. Jika proses penulisan data berhasil dilakukan sebelum terjadinya pemutusan koneksi, verifikasilah keadaan eksternal sebelum mencoba melakukannya lagi. Jika ada pesan lain yang sedang ditunggu atau proses penggenerasian data sudah berlangsung, gunakan kontrol dan informasi status yang tersedia, daripada mengasumsikan bahwa beberapa proses dapat berjalan secara bersamaan dalam chat yang sama. Panel pesan yang ditunggu memungkinkan Anda untuk memeriksa proses-proses yang masih tertunda. Kontrol pengelolaan data akan mencoba memberikan bimbingan pada batasan-batasan yang aman, setelah proses-proses yang sedang berlangsung selesai. Kedua operasi tersebut tidak akan membatalkan efek dari proses-proses yang telah selesai.

## Lampiran-lampiran, preview, dan artefak-artefak

Gunakan fitur pengendalian attachment untuk mengunggah file atau gambar yang didukung. Limit pengunggahan file adalah 32 MiB per attachment. Selain itu, batasan yang ditetapkan oleh sistem deployment/proxy mungkin membuat limit yang sebenarnya lebih kecil lagi. File yang diunggah disimpan di Controller, dan dapat diakses melalui model yang ada. Interpretasi gambar memerlukan model dan provider yang dapat menerima input berupa gambar. Pengunggahan file bukanlah cara untuk mendapatkan akses ke file lokal atau jarak jauh yang tidak berkaitan dengan file tersebut.

Saat meminta file yang dihasilkan, tentukan jalur penyimpanan, format, dan isi file tersebut. Pastikan bahwa file tersebut benar-benar ada sebelum membagikannya. Unduh atau lihat contoh file yang tersedia dari chat tersebut. File yang dihasilkan oleh Worker mungkin perlu ditransfer ke Controller atau disediakan melalui tautan file yang sesuai. Lihat [Tautan file](../guides/file-links.md).

Pemutahan artefak dapat menampilkan React, HTML, SVG, Markdown, dan Mermaid dalam bentuk panel samping, bukan hanya sebagai kode saja. Dalam pengaturan artefak Agent, mode “Normal” menggunakan instruksi standar. Mode “shadcn/ui” memberikan panduan terkait komponen-komponen yang digunakan. Sedangkan mode “Custom” memungkinkan pemutahan artefak dilakukan tanpa instruksi yang disertakan dalam artefak tersebut. Kode yang dihasilkan atau konten yang ditampilkan sebaiknya dianggap tidak dapat dipercaya; pastikan untuk meninjau kode tersebut sebelum menggunakannya di luar mode preview. Preview dan unduhan file berbasis Office berbeda dengan artefak UI yang dihasilkan.

Jangan mengunggah kredensial, kunci privat, atau dokumen-dokumen yang sebenarnya tidak berhak Anda kirimkan kepada penyedia model yang telah Anda pilih. Pemutusan koneksi dan penghapusan pesan-pesan tersebut merupakan hal yang terpisah dari proses penghapusan file asli di komputer.

## Pilihan/Penggunaan

Preferensi pengguna, seperti pengaturan alat-alat yang dapat digunakan dan shortcut keyboard, dikelola melalui WebUI. Preferensi-preferensi tersebut juga disimpan di server tempat aplikasi ini diimplementasikan. Anda dapat mengatur perilaku keyboard dengan mengakses menu Pengaturan. Perlu dicatat bahwa pengiriman pesan berbeda dengan pengetikan baris baru. Pengaturan alat-alat yang dapat digunakan juga perlu dilakukan secara terpisah dari pengaturan akses pengguna terhadap alat-alat tersebut. Lihat dokumen [Alat dan akses](permissions.md) serta [Memori dan konteks](context.md) untuk informasi lebih lanjut.
