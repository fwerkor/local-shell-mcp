<!-- i18n-source-sha256: e5ebd5f8cfb42332f4e38d63eabe47a6274ceacf919130202203bd85917f3469 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Alat-alat, mesin-mesin, dan izin-izin yang diperlukan.

## Lapisan otentikasi.

Alat yang tercantum dalam daftar tersebut tidak menjamin adanya izin untuk menggunakannya. Autentikasi yang efektif melibatkan berbagai faktor seperti batasan-batasan yang ditetapkan oleh Controller, skop akses yang dimiliki oleh entitas yang telah diverifikasi, kebijakan komputer, kemampuan Agent, serta persetujuan dari alat tersebut. Petunjuk-petunjuk yang diberikan saja tidak cukup untuk memastikan bahwa akses tersebut dapat dilakukan.

Mesin yang terdaftar, termasuk mesin Controller lokal ketika diaktifkan, secara default memiliki kemampuan untuk melakukan operasi baca/tulis pada data chat. Namun, pengaturan ini dapat dibatasi untuk penggunaan dalam konteks deployment yang sensitif. Nama mesin yang tidak diketahui tidak akan mendapatkan hak akses secara otomatis. Controller dapat dinonaktifkan untuk menghentikan proses eksekusi di lokasi tertentu, atau untuk menggunakan Workers yang berada di lokasi jarak jauh.

## Akses ke mesin

| Akses | Makna/Arti |
|---|---|
| Tidak ada | Operasi mesin tidak dapat dilakukan. |
| Hanya baca | Hanya operasi yang diklasifikasikan sebagai operasi hanya dapat dibaca saja yang diperbolehkan. Eksekusi shell/Python secara sembarangan bukanlah operasi yang hanya dapat dibaca saja. |
| Membaca/menulis | Memungkinkan proses pembacaan, perubahan, dan eksekusi yang diizinkan oleh pihak berwenang. Namun, masih ada batasan-batasan lain yang perlu dipatuhi. |
| Warisi | Gunakan nilai default yang berlaku untuk tingkat yang lebih tinggi, bukan nilai yang ditentukan secara eksplisit. |

![Izin dan mode persetujuan mesin dalam sebuah percakapan](../assets/chat/machine-permissions.png)

Atur nilai default global, penggantian per proyek, dan penggantian per chat dalam kontrol izin mesin. Penggantian pada percakapan mengungguli penggantian proyek, yang mengungguli default global. Agent dapat membatasi akses lebih lanjut per mesin atau melalui kebijakan default-nya; izin eksplisit Agent tidak dapat melewati batasan identitas terautentikasi atau Controller.

Contoh: kebijakan global baca/tulis, penggantian proyek hanya-baca, dan izin baca/tulis Agent menghasilkan akses hanya-baca pada chat proyek tersebut, kecuali kebijakan percakapan menggantinya secara eksplisit. Penggantian baca/tulis pada percakapan tetap tidak dapat melebihi batas hanya-baca Agent.

Penggunaan agen yang telah ditentukan waktu pelaksanaannya menggunakan kebijakan mesin milik agen tersebut, serta skema eksekusi yang telah disimpan. Agensi ini tidak mewarisi pengaturan-pengaturan biasa yang digunakan oleh mesin chat. Lihat [Tujuan dan Automasi](automation.md). Gunakan agen khusus untuk tugas-tugas yang tidak memerlukan intervensi manusia.

## Persetujuan terhadap alat tersebut

| Gaya/Style | Perilaku |
|---|---|
| Otomatis | Panggilan yang diizinkan dapat dilakukan tanpa perlu adanya persetujuan tambahan, kecuali jika ada kebijakan khusus yang mengharuskan hal tersebut. |
| Tinjau operasi berisiko | Controller meminta peninjauan terhadap operasi-operasi yang diklasifikasikan sebagai berbahaya. Operasi-operasi tersebut mencakup perintah shell yang bersifat sembarangan, serta banyak sekali panggilan eksternal lainnya. |
| Tinjau semua alat | Meminta persetujuan untuk pemanggilan alat-alat biasa. |

Pengaturan persetujuan chat dapat mewarisi default Agent dan global. Aturan penolakan atau persetujuan eksplisit yang sudah ada tetap berlaku. Agent anak tidak dapat melonggarkan mode persetujuan induknya. Persetujuan terpisah dari izin: menyetujui tindakan mesin yang ditolak tidak memberikan akses mesin.

Pertimbangkan argumen yang digunakan, tujuan, serta potensi efek samping sebelum memberikan persetujuan. Untuk proses kerja yang tidak dikontrol oleh manusia, atur pengaturan Agent dan kebijakan persetujuan dengan hati-hati. Persetujuan dari manusia dapat menghambat proses kerja. Jangan memperluas akses hanya untuk menghilangkan petunjuk yang diperlukan.

## Alat-alat MCP domestik dan eksternal.

Alat-alat native ini beroperasi pada Controller dan Workers yang telah terdaftar melalui LSM. Daftar alat tersebut mencakup berbagai fungsi seperti operasi file, shell dan pekerjaan tertentu, operasi browser dan GUI, pengenalan jarak jauh, sesi logis, serta fungsi-fungsi lainnya. Untuk informasi lebih lanjut mengenai struktur argumen yang digunakan oleh alat-alat tersebut, silakan merujuk ke [Tools reference](../reference/tools.md). Untuk informasi mengenai cara menggabungkan mesin-mesin jarak jauh, silakan merujuk ke [Remote workers](../guides/remote-workers.md).

Manajemen server MCP yang bersarang di WebUI. Konfigurasi yang didukung termasuk transportasi lokal dan HTTP jarak jauh, beserta variabel lingkungan atau header khusus untuk setiap server. Aktifkan kemampuan MCP eksternal dalam chat dan pada Agent yang relevan. Agent dapat menemukan, memeriksa, dan memanggil alat-alat eksternal yang tersedia; otorisasi dan persetujuan terhadap alat-alat tersebut tetap berlaku.

Alat MCP eksternal dapat beroperasi secara independen dari ACL mesin bawaan: API eksternal jarak jauh dapat mengubah sumber daya meskipun akses mesin lokal dinonaktifkan. Tinjau izin dan kredensial layanan eksternal secara terpisah. Jangan memasang server stdio yang tidak tepercaya pada Controller yang menyimpan berkas sensitif.

## Tanyakan kepada pengguna mengenai fitur-fitur yang dapat diaktifkan atau ditutup.

Ask User memungkinkan agen untuk meminta masukan dari manusia yang terstruktur, bukan sekadar menebak-nebak. Agen akan merespons dengan menggunakan kontrol yang ditentukan oleh pertanyaan-pertanyaan yang diajukan. Ini merupakan permintaan untuk mendapatkan informasi, bukan izin untuk mengabaikan alat yang ditolak. Ketika tugas tersebut tidak ditangani secara manual, agen perlu diberi petunjuk tentang cara menghadapi situasi yang tidak jelas, serta memeriksa interaksi-interaksi yang masih berlangsung sebelum menyimpulkan bahwa tugas tersebut telah selesai.

Penyusun konten ini juga menjelaskan berbagai fitur yang dapat dikontrol, seperti kemampuan pencarian melalui jaringan, penggunaan alat MCP eksternal, serta pengaturan memori. Fitur-fitur ini menentukan apa saja kemampuan yang dapat digunakan oleh model tersebut. Fitur-fitur ini terpisah dari mekanisme otorisasi. Dengan menonaktifkan suatu fitur, hasil-hasil yang telah dicapai sebelumnya tidak akan hilang. Pencarian melalui jaringan diaktifkan secara default, dan digunakan alat-alat yang hanya dapat membaca data saja, sebagaimana dijelaskan dalam [Network search](../guides/webui-network-search.md).

## Auditing dan verifikasi

Periksa panggilan alat-alat tersebut serta hasilnya dalam chat. Perluas informasi yang terkait dengan kegagalan yang terjadi saat mendiagnosis masalah. Log audit dari Controller mencatat aktivitas alat-alat native tersebut, sedangkan pekerjaan/sesi yang sedang berlangsung dapat dilihat melalui log tersebut. Jika respons API berhasil, berarti alat tersebut telah mengembalikan hasil yang diharapkan. Namun, hal ini belum tentu berarti bahwa operasi eksternal yang diminta telah berhasil mencapai tujuannya. Verifikasi kembali proses penulisan data, status pekerjaan jarak jauh, dan kondisi penyebaran hasilnya secara mandiri. Lihat [Audit Log](../guides/audit-log.md) untuk informasi lebih lanjut.
