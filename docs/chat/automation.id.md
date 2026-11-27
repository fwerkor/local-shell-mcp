<!-- i18n-source-sha256: 01c14c19cf5addf99299993b57542259bcb40bbfb13600758b516a86c89e716b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Tujuan-tujuan yang ingin dicapai, percakapan-percakapan yang direncanakan, serta pekerjaan-pekerjaan yang membutuhkan waktu lama untuk diselesaikan.

## Pilihlah mekanisme yang tepat.

| Mekanisme | Tujuan |
|---|---|
| Generasi percakapan biasa. | Membalas permintaan pengguna saat ini, termasuk pemanggilan alat-alat yang diperlukan untuk melakukan tugas tertentu. |
| Tujuan percakapan. | Melanjutkan rencana logis yang aktif di setiap batas perputaran model. |
| Percakapan yang ditetapkan secara teratur. | Mulai menggunakan agen tersebut dengan prompt yang telah disimpan, dalam ritme yang berulang. |
| Tugas atau proses yang berkelanjutan. | Melaksanakan perintah secara independen, tanpa perlu mengikuti permintaan model tertentu. |
| Subagent. | Serahkan tugas yang bersifat terbatas kepada thread Agent lainnya. |

Chat yang telah ditentukan jadwalnya bukanlah sebuah proses yang berkelanjutan. Sesi logis juga bukan merupakan percakapan atau proses yang terjadi di sistem operasi. Membatalkan sesi tersebut tidak berarti bahwa semua proses yang dimulai oleh alat-alat yang digunakan dalam sesi tersebut akan berakhir.

## Tujuan percakapan.

Untuk tugas yang membutuhkan waktu yang lama, mintalah agen untuk menentukan tujuan yang konkret dan menyusun rencana menggunakan alat-alat Logical Session. Rencana tersebut mencakup langkah-langkah yang perlu diambil serta status masing-masing langkah tersebut. Chat runtime dapat melanjutkan pelaksanaan rencana tersebut pada saat batas waktu model berlaku, tanpa perlu menunggu permintaan dari pengguna baru atau waktu yang ditentukan oleh MCP Live Workspace.

Periksa rencana dan perkembangannya. Anda dapat menghentikan, melanjutkan, atau membatalkan rencana tersebut menggunakan kontrol yang tersedia. Perluasan rencana hanya dapat dilakukan jika rencananya masih aktif dan memenuhi syarat untuk dilanjutkan. Rencana yang sudah selesai, terhalang, atau dibatalkan tidak boleh dilanjutkan lagi. Jika ada respons yang sama berulang-ulang tanpa adanya kemajuan, maka rencana tersebut akan dihentikan, bukan dilanjutkan secara berkelanjutan (saat ini, hal ini terjadi setelah terjadi tiga kali perubahan yang tidak signifikan). Cari solusi untuk masalah yang menghalangi rencana tersebut sebelum melanjutkannya.

Tentukan kriteria kesempurnaan proses tersebut. Misalnya: periksa repositori yang terkait, lakukan perbaikan yang diperlukan, jalankan rangkaian tes yang relevan, dan laporkan segala kegagalan yang terjadi. Mintalah agar Agent mencatat ID commit yang tepat serta hasil tesnya, bukan hanya menyatakan bahwa proses tersebut berhasil berdasarkan rencana yang dibuat oleh Agent sendiri.

Mekanisme klien MCP eksternal tersebut merupakan sesuatu yang terpisah dari mekanisme utama. Untuk informasi lebih lanjut mengenai proses penghubungan antara Logical Session dan Live Workspace, silakan lihat [Human Interface](../guides/human-interface.md).

## Buat chat yang ditanggalkan.

![Bilah samping chat terjadwal dengan contoh jadwal yang dinonaktifkan](../assets/chat/scheduled-chats.png)

Buka pengelolaan percakapan yang telah dijadwalkan. Buatlah jadwal dengan memberikan nama yang deskriptif, agen yang akan bertugas, waktu zona, serta ritme percakapan. Pilih target pembicaraan yang diinginkan; jika perlu, pilih proyek tertentu untuk percakapan baru tersebut. Simpan dan aktifkan jadwal tersebut. Gunakan fitur pengendalian eksekusi manual untuk memeriksa konfigurasi sebelum menggunakannya.

Jadwal yang didukung mencakup jadwal harian, mingguan, serta eksekusi secara terus-menerus setelah terjadi peristiwa tertentu. Eksekusi secara terus-menerus dimulai setelah terjadi peristiwa tersebut, setelah adanya penundaan yang telah ditentukan. Penundaan yang nol dapat menyebabkan beban kerja pada penyedia layanan dan mesin yang meningkat secara berkelanjutan. Jadwal yang berulang biasanya memiliki interval minimal lima menit. Gunakan zona waktu IANA yang jelas, seperti `Asia/Shanghai` atau `UTC`. Periksa hasil eksekusi setelah proses penyimpanan selesai.

Contoh cron untuk pukul 09:00 pada hari kerja:

```text
0 9 * * 1-5
```

Hal ini menggunakan zona waktu yang dipilih, bukan harus zona waktu sistem milik Controller. Periksa apakah zona waktu yang dipilih mengikuti sistem penyesuaian waktu yang disebut “daylight-saving”.

## Tujuan percakapan

- **Percakapan baru setiap eksekusi:** Mulailah percakapan terpisah untuk setiap kejadian yang terjadi. Hal ini sangat berguna untuk laporan-laporan yang bersifat independen.
- **Gunakan kembali satu percakapan:** Buatlah percakapan baru pada pertemuan pertama, lalu gunakan percakapan tersebut untuk pertemuan-pertemuan berikutnya. Hal ini sangat berguna untuk pemantauan secara terus-menerus.
- **Gunakan percakapan yang ada:** Pilih sebuah percakapan yang sudah ada, sehingga percakapan tersebut dapat menerima bagian-bagian tertentu yang ditentukan secara teratur.

Percakapan yang telah digunakan kembali atau yang sudah ada sebelumnya dapat berkembang lebih lanjut, dan memerlukan proses pengurangan informasi yang tidak perlu. Pilihlah percakapan yang terpisah jika konteks historisnya tidak diperlukan. Jadwal eksekusi tergantung pada apakah Agent yang dipilih masih ada dan dapat digunakan atau tidak.

## Izin yang tidak dikelola dengan baik

Eksekusi terjadwal dimiliki Controller dan menggunakan nama scope yang telah diotorisasi dan disimpan, bukan menyimpan token login browser. Simpan atau jalankan jadwal secara manual untuk mengotorisasinya bila diperlukan. Izin mesin Agent yang ditentukan berlaku; penggantian izin mesin biasa pada proyek atau chat bukan kebijakan mesin jadwal. Batasan Controller, otorisasi tersimpan, kemampuan alat, dan persetujuan alat tetap berlaku.

Untuk server MCP eksternal yang memerlukan autentikasi, login interaktif tidak otomatis berarti ada izin yang dapat diperbarui untuk eksekusi tanpa pengawasan. Jika UI jadwal menyatakan perlu autentikasi ulang atau akses tanpa pengawasan, selesaikan kredensial khusus server atau hapus ketergantungan tersebut sebelum mengaktifkan jadwal. Jangan menggunakan kembali token browser sebagai pengganti.

Gunakan agen yang hanya dapat melakukan tugas pemantauan saja. Jelaskan secara eksplisit target yang diizinkan, output yang diinginkan, serta tindakan-tindakan yang perlu dihindari. Jika tugas yang direncanakan memerlukan input atau persetujuan manusia, periksa interaksi-interaksi yang sedang berlangsung. Jangan menganggap bahwa eksekusi tugas tanpa pengawasan berarti adanya akses yang tidak terbatas. Contoh pesan pemantauan:

```text
Periksa pekerjaan pelatihan yang ditentukan tersebut, serta log-log yang terkait dengannya.
Laporkan langkah yang sedang dilakukan, jumlah kerugian, laju proses, waktu yang diperkirakan untuk menyelesaikan pekerjaan, serta segala kesalahan yang terjadi.
Jangan mengubah file yang ada, jangan memulai proses kerja lagi, dan jangan mulai melakukan pekerjaan baru.
Jika data tersebut tidak tersedia, sebutkan secara rinci alasan di balik ketidakmampuan untuk memperoleh data tersebut.
```

## Siklus hidup dan proses pemulihan

Controller menyimpan informasi mengenai jadwal pelaksanaan tugas, status proses yang sedang berlangsung, serta transaksi yang terjadi. Hal ini dilakukan untuk menghindari terjadinya pengulangan proses yang sama. Tidak perlu ada tab browser yang tetap terbuka. Jangan menganggap bahwa semua proses yang gagal dilaksanakan akan dilaksanakan kembali, atau bahwa semua data eksternal akan tetap tersimpan setelah Controller dihentikan. Periksa informasi mengenai proses yang telah selesai, proses yang sedang berlangsung, serta chat yang terkait setelah terjadi gangguan.

Hapus rencana tersebut agar tidak ada lagi kejadian otomatis di masa depan. Periksa secara terpisah setiap proses yang sedang berlangsung; menghentikan rencana tersebut tidak menjamin bahwa proses tersebut akan dibatalkan atau tidak akan dilakukan lagi. Hapus rencana-rencana yang sudah tidak diperlukan lagi, dan batalkan hak akses agen yang tidak diperlukan.

Sebuah pekerjaan atau terminal yang dibuat oleh WebUI Agent dapat bertahan setelah proses model-response selesai. Pemulihan kontroler saja tidaklah cukup untuk menghentikan pekerjaan tersebut. Penghentian secara eksplisit, hilangnya izin untuk menggunakan mesin tersebut, atau berakhirnya masa berlakunya izin tersebut dapat menyebabkan pekerjaan yang dilakukan oleh Agent dibatalkan. Jika Worker tidak tersedia, maka pembatalan pekerjaan tersebut mungkin akan tetap berlangsung sampai Worker kembali tersedia. Periksa sendiri pekerjaan atau terminal tersebut sebelum menyatakan bahwa eksekusi pekerjaan telah berakhir. Agent hanya dapat mengirimkan atau menghentikan pekerjaan yang ditangani oleh dirinya sendiri melalui alat WebUI yang aman. Klien MCP eksternal tetap memiliki semantiknya sendiri.

Alat-alat latar belakang agen dan tugas-tugas subagen memiliki siklus hidupnya masing-masing. Hasil dari suatu tugas mungkin masih dalam tahap penantian pengiriman, meskipun prosesnya sudah selesai. Periksa panel tugas latar belakang tersebut untuk mendapatkan hasilnya, atau biarkan sistem yang telah dikonfigurasi untuk melanjutkan proses tersebut. Jangan mulai menciptakan tugas yang berulang hanya karena hasilnya belum terlihat.

Untuk perintah-perintah yang perlu berlangsung lebih lama dari waktu yang ditentukan oleh suatu alat tertentu, gunakan tugas-tugas yang dilacak oleh LSM atau terminal yang bersifat persisten. Simpan hasil eksekusi perintah tersebut ke dalam file log, catat identitas tugas-tugas tersebut, dan periksa perkembangan tugas-tugas tersebut secara berkala. Lihat [Pola penggunaan](../guides/usage-patterns.md) untuk informasi lebih lanjut.
