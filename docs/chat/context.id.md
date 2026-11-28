<!-- i18n-source-sha256: 214687d6067b7dc2dd2b6eec1a207aa50be3ab9550d081f8a60e3013684c0250 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Penggunaan memori, konteks, dan token

## Tiga jenis negara yang berbeda

| Negara/Negara Bagian | Tujuan |
|---|---|
| Sejarah percakapan/diskusi | Pesan-pesan asli dan aktivitas yang dilakukan oleh alat-alat yang digunakan oleh Controller disimpan dalam bentuk yang terpisah. |
| Jendela Konteks | Subset dari instruksi-instruksi, skema alat, riwayat data, ringkasan data, dan data lainnya yang dikirim dalam permintaan model tertentu. |
| Memori yang berkelanjutan | Fakta dan preferensi yang dapat digunakan kembali, yang dapat diakses dalam berbagai percakapan di lingkup memori yang relevan. |

Sebuah percakapan yang telah disimpan dalam jangka waktu yang lama dapat melebihi batas jangkauan model tersebut, tanpa membuat seluruh riwayat percakapan hilang. Memori tidak berarti bahwa seluruh riwayat percakapan akan dikirim ke setiap permintaan yang diajukan oleh model.

## Mengelola memori

![Bilah samping pengelolaan memori dengan entri contoh](../assets/chat/memory-management.png)

Memori dipasang secara default, kecuali jika dimatikan oleh pengaturan pengguna, tombol toggle chat, atau pembatasan yang ditetapkan pada fitur deployment/Agent. Gunakan halaman manajemen memori untuk memeriksa dan mengedit data yang disimpan. Mintalah Agent untuk mengingat fakta-fakta penting, konvensi proyek, atau preferensi pengguna. Pastikan hasilnya sesuai dengan apa yang tercatat dalam antarmuka memori.

Saat mengedit entri memori, gunakan kunci yang terdiri dari huruf-huruf kecil dan tanda under saja (contohnya, `repository_conventions`). Batas panjang entri memori secara default adalah 10.000 karakter. Namun, sebuah instalasi dapat mengonfigurasi batas-batas penyimpanan memori tersebut. Jika ada entri yang ditolak, periksa kesalahan yang terjadi, daripada membagi kata sandi ke dalam beberapa kunci yang berbeda.

Memori dapat menggunakan pool perangkat lunak yang dapat digunakan bersama-sama oleh beberapa aplikasi, atau menggunakan skala yang khusus untuk setiap agen, tergantung pada konfigurasi agen tersebut. Jangan menyimpan kunci API, kata sandi, atau data sensitif lainnya dalam memori. Menonaktifkan memori akan mencegah penggunaan data tersebut dalam skala yang relevan. Hal ini berbeda dengan menghapus entri-entri yang sudah disimpan atau menghapus catatan percakapan dari sejarah percakapan.

Ketika model tersebut terpapar, ia menggunakan fungsi `set_memory` untuk menciptakan atau memperbarui entri-entri yang ada. Nilai kosong akan menghapus entri tersebut. Fungsi `find_memory` digunakan untuk mengambil entri-entri berdasarkan kueri atau kunci tertentu. Kueri kosong akan menghasilkan daftar entri yang tersimpan. Flag opsi `include_conversations` memungkinkan pencarian teks dari percakapan-percakapan lainnya juga. Penggunaan paginasi dilakukan dengan menggunakan parameter `page` (default: 1) dan `limit` (default: 10, maksimum: 50). Proses pengambilan data berdasarkan riwayat percakapan ini mencari teks dari percakapan-percakapan tersebut, bukan catatan invokasi alat secara langsung. Proses pengambilan data dilakukan berdasarkan tingkat relevansi, jadi gunakan nama atau istilah yang tepat, dan perbaikilah kueri jika diperlukan.

Proses penyisipan informasi secara otomatis dalam memori/keahlian tetap stabil, sepanjang percakapan berlangsung. Hal ini dilakukan agar prefiks prompt yang dapat digunakan kembali dapat dipertahankan. Mengedit data yang telah disimpan tidak akan mempengaruhi data yang sudah disisipkan sebelumnya. Pengambilan data secara eksplisit hanya dilakukan untuk mendapatkan data yang sedang tersimpan saat ini. Jika diperlukan konteks baru, maka percakapan dapat dimulai kembali.

## Kapasitas kontekstual

Setkan batasan konteks aktual untuk setiap model dalam salurannya masing-masing. Controller memperkirakan input yang dapat dilihat oleh model, dan menyisakan ruang untuk outputnya. Tingkat penghematan anggaran saat ini adalah 85%, dengan sisanya sebesar 5%. Tingkat penghematan ini dapat berubah sesuai dengan konfigurasi model dan waktu eksekusi yang digunakan. Jumlah tersebut mungkin bersifat perkiraan, terutama untuk tokenizer yang belum dikenal, permintaan yang bersifat multimodal, atau skema spesifik dari penyedia layanan tertentu.

Komposisi konteks tersebut dapat mencakup instruksi sistem, konfigurasi agen, definisi alat-alat yang digunakan, file tambahan, pesan-pesan sebelumnya, serta hasil-hasil yang diperoleh dari penggunaan alat-alat tersebut. Penyedia layanan mungkin menggunakan tokenizer yang berbeda, atau menghitung token internal tambahan. Anggaplah tampilan tersebut sebagai panduan operasional, bukan sebagai jaminan dari penyedia layanan.

## Pengompakan otomatis

Ketika anggaran konteks memerlukan pengurangan ukuran data yang disimpan, Controller akan membuat atau memperbarui ringkasan informasi dari data yang sudah lama disimpan. Ringkasan tersebut mencakup berbagai hal seperti tujuan, batasan-batasan, keputusan-keputusan yang diambil, perkembangan proses, identifikator-identifikator yang relevan, hasil-hasil penggunaan alat-alat tertentu, serta tindakan-tindakan selanjutnya. Sejarah asli yang disimpan tetap dapat dilihat; ringkasan tersebut merupakan versi perbandingan yang dihasilkan oleh model, bukan reproduksi yang sempurna.

Proses kompaksi dilakukan sebelum permintaan berikutnya. Jika proses sumberan tidak berhasil, mesin akan mencoba lagi sesuai dengan mekanisme penanganan kesalahan yang ada. Tidak boleh membiarkan proses berlanjut hanya karena input yang sudah terlalu besar. Periksa status kompaksi dan kesalahan yang terjadi jika proses tidak dapat dilanjutkan. Pesan-pesan terbaru serta hubungan antara tool-call dan hasilnya harus tetap konsisten. Hasil dari tool yang telah selesai seharusnya tidak diubah secara berkala hanya untuk mengurangi ukuran konteksnya.

Satu attachment atau hasil dari tool yang sangat besar masih bisa melebihi batas anggaran yang ditetapkan. Mohon gunakan output yang dibatasi, rentang file tertentu, atau versi ringkas dari hasil tersebut. Simpan hasil yang besar dalam file, dan ambil bagian-bagian tertentu dari hasil tersebut, bukan memasukkannya secara berulang-ulang ke dalam konteks model.

## Penggunaan sumber daya secara kumulatif dan hitungan cache juga perlu diperhatikan.

Tampilan penggunaan sesi dan jendela konteks menjawab pertanyaan yang berbeda. Penggunaan input/output terakumulasi selama proses permintaan berlangsung, termasuk konteks yang digunakan berulang-ulang. Metrik cache menggambarkan penggunaan cache yang dilaporkan oleh penyedia layanan, jika tersedia. Ukuran konteks model mencerminkan jendela aktif model tersebut, dan tidak dihitung setiap kali permintaan dilakukan.

Misalnya, sebuah permintaan yang mengandung 20.000 token input, diikuti oleh permintaan lain yang mengandung 25.000 token input, akan menghabiskan total 45.000 token input. Namun, permintaan kedua hanya menggunakan sekitar 25.000 token dari kapasitas konteksnya. Token yang disimpan dalam cache tidaklah gratis, kecuali jika penyedia layanan menetapkan demikian. Batasan kapasitas konteks model yang lebih besar akan mengubah kapasitasnya, bukan penggunaan sumber daya yang telah digunakan sebelumnya.

Proses kompaksi dapat mengurangi tingkat penggunaan sumber daya saat ini, namun pada saat yang sama, hal tersebut juga akan meningkatkan konsumsi model. Mengganti model akan mengubah batasan konteks yang berlaku; namun, konsumsi sebelumnya tidak akan hilang. Jika penyedia tidak menyertakan data penggunaan atau metadata cache secara lengkap, maka estimasi dan metrik yang diperoleh mungkin tidak lengkap. Untuk tujuan rekonsiliasi keuangan, gunakan data pembayaran dan harga yang disediakan oleh penyedia tersebut, bukan hanya informasi yang ditampilkan dalam LSM saja.

## Kurangi biaya dan pertahankan konteks yang berguna.

Pastikan agar instruksi yang diberikan tetap stabil. Hindari penggunaan alat yang menghasilkan output yang terlalu besar secara tidak perlu. Gunakan metode pencarian yang efektif saja. Mulailah percakapan terpisah untuk masalah-masalah yang tidak relevan. Ketika perlu melakukan penyerahan tugas, simpanlah informasi yang penting dalam bentuk checkpoint yang ringkas, termasuk rute yang tepat, ID commit, hasil yang diperoleh, serta pertanyaan-pertanyaan yang masih belum terjawab. Verifikasi kembali fakta-fakta penting tersebut dengan sumber asli atau hasil yang dihasilkan oleh alat tersebut, bukan hanya berdasarkan ringkasan yang dibuat secara otomatis.
