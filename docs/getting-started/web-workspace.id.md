<!-- i18n-source-sha256: 01cf883cb71925e93fabc21d32315ef8c869ee2ea548e54a0347e2f6b730a327 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Pengantar cepat mengenai WebUI Chat

LSM web workspace yang terintegrasi ini mencakup fitur chat AI, proyek-proyek, agen-agen, serta halaman operasional yang digunakan oleh Controller. LSM web workspace ini dijalankan menggunakan Python Controller, dan menggunakan sistem autentikasi serta basis data SQLite untuk pengelolaan data. Tidak diperlukan server chat terpisah. Klien-klien MCP eksternal seperti [ChatGPT](chatgpt-connector.md) dan [Gemini](gemini-spark.md) tetap didukung.

## 1. Jalankan Controller

Ikuti langkah-langkah dalam [instalasi cepat](quickstart.md) sesuai dengan platform yang Anda gunakan. Pastikan bahwa WebUI sudah diaktifkan, dan gunakan penyimpanan permanen. Berikut adalah pengaturan default yang umum digunakan:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

Setelah Anda meng ekspor lingkungan layanan Anda, mulailah menjalankan Controller tersebut.

```sh
local-shell-mcp --mode mcp
```

Untuk proses peluncuran yang menggunakan satu baris kode, gunakan eksekusi yang telah diunduh tersebut. Alat Controller yang sudah terinstal digunakan untuk mengelola frontend yang telah dikompilasi; alat pembangun JavaScript hanya diperlukan untuk proses pembangunan sumber kode. Lihat [Instruksi pembangunan WebUI](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## 2. Buka ruang kerja di browser

Buka situs web `http://127.0.0.1:8765/ui` dari host Controller tersebut. Atau, Anda dapat mengaksesnya melalui URL HTTPS yang telah dikonfigurasi, dengan akhiran `/ui`. Masuklah menggunakan autentikasi LSM yang telah ditetapkan untuk deployment tersebut. Gunakan protokol HTTPS untuk akses jarak jauh. Halaman chat dan halaman kontrol memiliki asal yang sama.

## 3. Tambahkan kanal model

Buka menu pemilihan model dan pengelolaan saluran. Tambahkan saluran API, atau hubungkan akun yang didukung oleh OpenAI. Untuk endpoint yang kompatibel dengan OpenAI, masukkan nama saluran, pilih Chat Completions, masukkan URL dasar API serta kredensialnya. Selanjutnya, cari model yang diinginkan, atau masukkan ID model yang sudah diketahui secara manual. Simpan konfigurasi tersebut, lalu pilih model yang diinginkan.

Untuk layanan inferensi lokal, gunakan alamat yang dapat diakses dari Controller, bukan hanya melalui browser Anda saja. Sebagai contoh, `http://127.0.0.1:8080/v1` merupakan alamat yang tepat jika layanan inferensi tersebut berada di alamat tersebut dalam namespace jaringan Controller. Lihat [Channels and models](../chat/channels.md) untuk informasi mengenai protokol, otentikasi akun, penemuan model, dan batasan-batasan konteks.

## 4. Jalankan tugas pertama

Mulailah berbicara dengan mengajukan pertanyaan sederhana, agar dapat menguji konektivitas model tersebut. Setelah itu, coba gunakan alat yang hanya berfungsi untuk membaca data saja.

```text
Sebutkan file-file yang ada di akar lingkungan Controller.
Beritahu saya yang mesin apa yang Anda inspeksi, dan rangkumkan hasilnya.
Jangan mengubah file apa pun, atau menjalankan proses penulisan data ke dalam file tersebut.
```

Periksa hasil yang diberikan oleh alat tersebut. Jika ada alat yang hilang, periksa pengaturan alat dalam chat, pengaturan agen, serta izin yang dimiliki oleh mesin tersebut. Gunakan agen yang telah disimpan untuk tugas-tugas yang berulang, dan atur aksesnya secara eksplisit. Lihat [Alat dan izin](../chat/permissions.md).

![Chat melalui WebUI dengan contoh percakapan demonstratif](../assets/chat/chat-workspace.png)

Screenshot-screenshot yang terdapat dalam panduan ini, serta halaman-halaman berikutnya, diambil dari contoh penggunaan Controller yang bersifat demonstratif saja. Screenshot-screenshot tersebut tidak mengandung informasi mengenai kredensial produksi atau percakapan-percakapan yang terjadi. Label-label pada antarmuka pengguna dalam bahasa Inggris mungkin berbeda dengan label yang digunakan dalam bahasa yang dipilih.

## 5. Jelajahi ruang kerja

| Wilayah/Area | Untuk apa menggunakan alat tersebut? |
|---|---|
| Chat dan proyek-proyek | Mulai atau cari chat yang ada, organisasikan proyek-proyek, tag-tag, serta catatan pesan-pesan yang digunakan dalam proses kerja. |
| Agents | Model, instruksi, dan konfigurasi alat yang dapat digunakan kembali. |
| Memori dan Keterampilan | Mengelola pengetahuan dan instruksi yang dapat digunakan kembali. |
| Chat yang ditetapkan secara teratur. | Jalankan agen yang telah disimpan, dengan menggunakan prompt yang berulang-ulang. |
| File dan terminal | Periksa atau lakukan proses pengelolaan pada lingkungan Controller dan Worker. |
| Desktop | Memeriksa dan mengontrol sesi GUI jarak jauh yang didukung oleh sistem ini. |
| Sesi kerja, pekerjaan, dan proses audit | Memeriksa tugas-tugas yang perlu diselesaikan, perkembangan proses eksekusi tugas, serta aktivitas yang dilakukan oleh alat-alat yang digunakan dalam proses tersebut. |
| Mesin-mesin dan perangkat eksternal yang menggunakan protokol MCP. | Mengelola pekerja dan server MCP yang bersarang di dalamnya |

Set of kontrol yang diperlukan tergantung pada cara penginstalannya, akun yang digunakan, serta kemampuan yang disediakan oleh sistem tersebut. Menutup browser tidak akan menghentikan proses generasi data di server; gunakan fitur “stop” ketika Anda perlu menghentikan proses kerja tersebut.

## Langkah-langkah selanjutnya…

Baca [WebUI Chat guide](../chat/index.md) untuk informasi lengkap mengenai alur kerja sistem ini. Selain itu, baca juga [Administration and troubleshooting](../chat/administration.md) untuk informasi mengenai pengaturan produksi, pembuatan cadangan data, dan cara mengatasi kesalahan yang terjadi.
