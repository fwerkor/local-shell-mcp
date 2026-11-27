<!-- i18n-source-sha256: d33afa60bf803b367c950dbadf80fa77167568a970adcac204cdea7e9e965e45 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Agen dan Keterampilan

## Kapan sebaiknya membuat seorang Agen?

Chat model langsung sangat berguna untuk pertanyaan atau tugas yang bersifat sementara saja. Agent merupakan konfigurasi yang dapat digunakan berulang-ulang; dapat digunakan dalam chat yang dijadwalkan, atau dapat didelegasikan kepada agen lain. Agen-agen yang berbeda mungkin menggunakan saluran komunikasi, model, instruksi, dan kebijakan akses yang berbeda pula. Mereka memiliki Controller yang sama, tetapi tidak selalu memiliki ruang memori atau alat yang sama.

## Konfigurasi sebuah Agensi

Kelola agen tersebut melalui WebUI. Buatlah agen baru, berikan nama yang mudah dikenali kepada agen tersebut, dan pilih modelnya. Tuliskan instruksi-instruksi yang diperlukan untuk menjalankan tugas tersebut, termasuk output yang diinginkan, batasan-batasan yang ada, serta persyaratan verifikasi yang perlu dipenuhi. Konfigurasikan kemampuan-kemampuan yang diperlukan oleh agen tersebut. Setelah selesai, simpan konfigurasi tersebut, lalu mulailah proses percakapan baru dengan agen tersebut.

![Agent Builder with instructions, tools, approval, and Skill settings](../assets/chat/agent-builder.png)

Sebagai contoh, seorang reviewer di repositori mungkin memiliki instruksi seperti ini:

```text
Periksa perubahan-perubahan yang terjadi dibandingkan dengan versi utama saat ini.
Tinjau repositori dan hasil pengujian sebelum membuat kesimpulan.
Jangan mengedit file, melakukan push commit, atau melakukan deploy apa pun.
Laporkan temuan-temuan yang konkret, beserta rute dan bukti-buktinya.
```

Instruksi tersebut memang berguna untuk mengarahkan perilaku seseorang, tetapi instruksi tersebut bukanlah batasan yang menentukan apa yang boleh atau tidak boleh dilakukan. Berikan akses mesin hanya untuk membaca saja, dan hindari penggunaan kemampuan MCP eksternal yang tidak diperlukan, jika peninjau tidak ingin mengubah apa pun. Lihat [Alat dan izin](permissions.md).

Sebaiknya menggunakan agen-agen yang terpisah untuk tugas-tugas yang berbeda, seperti pengawasan kode, implementasi, dan operasional. Berikan setiap agen akses yang minimal yang memungkinkan mereka melakukan tugas-tugas tersebut. Selain itu, berikan model yang sesuai dengan peran masing-masing agen. Jika sebuah agen tidak dapat dimulai, pastikan saluran komunikasi dan model yang digunakan oleh agen tersebut masih berfungsi dengan baik sebelum mengubah pengaturan-pengaturan yang tidak relevan.

## Skills

Paket keterampilan tersebut berisi instruksi-instruksi yang dapat digunakan kembali, serta file-file terkaitnya. Biasanya, paket ini disimpan dalam format `SKILL.md`. Keterampilan-keterampilan tersebut dapat dikelola melalui WebUI; keterampilan-keterampilan yang relevan dapat diaktifkan, sehingga dapat digunakan oleh Agent atau chat. Model dapat mendeteksi dan memuat konten keterampilan tersebut ketika diperlukan. Sebuah keterampilan dapat menjelaskan proses kerja, memberikan contoh-contoh, atau berisi skrip-skrip tertentu. Namun, keterampilan tersebut tidak secara otomatis menjalankan skrip-skrip tersebut, maupun memberikan izin tambahan kepada mesin.

Periksa kemampuan-kemampuan yang diimpor sebelum mengaktifkannya. Lakukan penanganan terhadap instruksi dan file-file tersebut sebagaimana halnya kode atau prompt dari pihak ketiga lainnya. Nama dan deskripsi setiap kemampuan harus cukup spesifik agar model dapat mengenalinya dengan mudah. Selain itu, hindari penggunaan referensi yang terlalu panjang; sebaliknya, gunakanlah alur kerja yang lebih kecil namun tetap dapat digunakan secara mandiri. Mengenai registri di sisi Controller dan cara memanggil alat-alat tersebut, baca lebih lanjut di [Skills](../guides/skills.md).

Konteks keterampilan dan memori secara otomatis dicatat untuk digunakan dalam percakapan, sehingga tidak perlu menulis ulang prompt sistem setiap kali terjadi percakapan. Perubahan pada skala keterampilan dapat berdampak pada hasil percakapan; gunakan konteks yang baru saat menguji perubahan yang telah dilakukan. Keterampilan yang dimasukkan secara sengaja berbeda dari snapshot awal yang digunakan dalam percakapan.

## Delegasi dan subagen

Agen dapat membagikan tugas-tugas yang bersifat terbatas kepada subagen, apabila kemampuan tersebut tersedia. Anak agen dapat menggunakan agen yang telah dikonfigurasi, namun tetap memiliki thread eksekusi sendiri untuk melakukan tugasnya. Agen induk bertugas mengkoordinasikan proses tugas tersebut, membaca hasil kerja anak agen, dan melanjutkan thread eksekusi yang telah disimpan oleh anak agen tersebut. Aktivitas anak agen dapat diinspeksi dari konteks percakapan yang dilakukan oleh agen induk. Namun, tampilan aktivitas anak agen tersebut bukanlah chat yang dapat diedit secara independen.

Gunakan mekanisme delegasi untuk tugas-tugas yang dapat dipisahkan, seperti evaluasi yang terpisah, area file yang berbeda, atau penyelidikan terhadap hipotesis yang berbeda. Berikan subagen tujuan yang jelas, skala tugas, dan hasil yang diharapkan. Hindari penulisan data ke file yang sama secara bersamaan, kecuali jika tugas tersebut benar-benar dikoordinasikan oleh “Agent” induk.

Delegasi harus tetap berada dalam batas-batas yang diizinkan oleh pihak induk. Delegasi tidak diperbolehkan memiliki akses ke mesin atau layanan MCP yang tidak dapat digunakan oleh pihak induk. Kebijakan persetujuan dari delegasi tidak boleh melemahkan kebijakan pihak induk. Tugas-tugas yang dilakukan oleh delegasi dapat menggunakan token model dan waktu secara mandiri. Oleh karena itu, perlu memantau aktivitas dan hasil kerja delegasi saat mengevaluasi biaya dan kemajuan pekerjaan tersebut.

## Alat-alat, tindakan, dan artefak

Agent Builder menyediakan koleksi alat yang tersedia serta kemampuan konfigurasi yang canggih. Pilih saja fitur-fitur yang benar-benar Anda butuhkan. Untuk tindakan HTTP yang dijelaskan dalam OpenAPI schema, periksa dulu endpointnya, persyaratan autentikasi, dan operasi-operasi yang diperbolehkan sebelum menghubungkan tindakan tersebut. Setiap tindakan dapat memiliki autentikasi sendiri; izin dari mesin tidak dapat memberikan otorisasi atau membatalkan kredensial API pihak ketiga. Periksa respons dari tindakan tersebut sebelum menganggap bahwa perubahan yang dilakukan sudah lengkap.

Untuk konten UI yang dihasilkan, atur proses rendering artefaknya sesuai dengan petunjuk yang terdapat dalam [Conversations and projects](conversations.md). Kode yang dihasilkan bukanlah bagian dari ekstensi yang dapat dipercaya dari Controller.

## Contoh template agen praktis

- **Penyelidai yang hanya dapat membaca data saja:** Melakukan pemeriksaan terhadap log dan sumber data yang digunakan. Membandingkan bukti-bukti yang ada, serta melaporkan penyebabnya. Tidak diperbolehkan melakukan modifikasi apa pun pada data tersebut.
- **Implementasi Agent:** Edarkan repositori yang diperlukan, jalankan tes-tes yang ditargetkan, laporkan perbedaan yang terjadi serta kesalahan-kesalahan yang belum terpecahkan. Perlu mendapatkan persetujuan untuk melakukan operasi-operasi yang bersifat sensitif, jika memang diperlukan.
- **Monitoring Agent:** Melakukan pemeriksaan pada mesin-mesin yang ditentukan, serta melaporkan status, kesalahan, dan perkembangan pekerjaan yang sedang dilakukan. Tidak boleh memulai kembali proses-proses tertentu, kecuali jika diizinkan secara eksplisit.
- **Agen Penelitian:** Memungkinkan pencarian informasi di jaringan, mengutip dokumen asli, membedakan bukti dari inferensi yang dibuat secara otomatis, dan menggunakan alat-alat mesin hanya bila diperlukan.

Template-template tersebut merupakan instruksi saja, bukan pengaturan yang sudah terdefinisi sebelumnya. Periksa kembali hak istimewa dan kemampuan masing-masing agen, agar sesuai dengan tugas yang dimaksudkan untuknya.
