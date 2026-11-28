<!-- i18n-source-sha256: 158a01475edc97cea1a70bc0d7b9a7330f7240dce14e7269635e675d044eedae -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Kanal-kanal dan model-modelnya

## Buatlah sebuah saluran komunikasi.

Buka alat pilihan model di Chat, lalu masuk ke halaman pengelolaan saluran. Pilih opsi **Menambahkan saluran**, pilih jenis koneksi yang diinginkan, masukkan informasi yang diperlukan, lalu simpan. Pilih model yang sesuai untuk digunakan dalam chat baru. Untuk agen khusus, pilih saluran dan model yang diinginkan dalam pengaturan agen tersebut.

Kanal-kanal tersebut dimiliki oleh Controller, bukan oleh pengguna individu. Pada implementasi yang telah diverifikasi, manajemen kanal memerlukan akses berdasarkan scope `admin:config`. Administrator dapat mengonfigurasi kanal-kanal bersamaan, tanpa perlu mendistribusikan kunci API kepada pengguna chat.

![Tambahkan saluran model ke dalam konfigurasi saluran yang sebenarnya](../assets/chat/channel-settings.png)

Saluran API yang normal memiliki nama, protokol penyedia layanan, URL dasar, kredensial, serta identifikasi model. Gunakan kunci API yang diberikan untuk endpoint yang dipilih, bukan kata sandi akun LSM Anda. LSM melakukan permintaan dari Controller; URL yang berfungsi di laptop Anda mungkin tidak akan berfungsi di Controller.

| Protokol | Contoh URL dasar API: | Gunakanlah. |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | Gateway percakapan yang kompatibel dengan OpenAI, serta server inferensi lokal. |
| OpenAI Responses | `https://api.openai.com/v1` | Sebuah gateway yang digunakan untuk mengakses API Responses. |
| Penduduk asli antropis | `https://api.anthropic.com/v1` | API yang kompatibel dengan Anthropic Messages. |
| Asli Google Gemini | `https://generativelanguage.googleapis.com/v1beta` | API yang kompatibel dengan Gemini generateContent. |

Gunakan URL dasar yang diperlukan oleh penyedia layanan tersebut, bukan URL lengkap seperti `/chat/completions`. Penyedia layanan yang mengklaim kompatibilitas dengan OpenAI mungkin hanya mendukung Chat Completions, tetapi tidak mendukung Response, panggilan alat, penggunaan streaming, input multimodal, atau opsi penalaran. Pilihlah protokol yang benar-benar didukung oleh penyedia layanan tersebut. Contoh URL merupakan contoh protokol saja, bukan jaminan bahwa akses tersebut gratis atau tersedia.

## Ujung akhir lokal dan kustom.

Untuk server yang kompatibel dengan OpenAI yang berada di Controller itu sendiri, URL dasarnya mungkin adalah `http://127.0.0.1:8080/v1`. Ketika berjalan dalam Docker, “loopback” merujuk pada kontainer tersebut, bukan host fisik. Gunakan alamat yang dapat diakses dari namespace jaringan Controller. Pendaftaran Worker secara remote saja tidak cukup untuk membuat API inferensi tersebut dapat digunakan.

Validator URL model memerlukan protokol HTTPS, kecuali untuk HTTP pada host-loopback (`localhost`, `127.0.0.1`, `::1`). Endpoint HTTP yang berada di LAN atau nama layanan Docker harus ditampilkan melalui gateway HTTPS. Penggunaan endpoint pribadi Hosted Chat tidak dapat digunakan. URL dasar tidak boleh mengandung kredensial, fragmen, atau string kueri.

Gunakan TLS untuk titik akhir yang berada di lokasi jauh. Batasi akses hanya ke gateway-gateway pribadi yang dapat dipercaya. Periksa identifikasi model tersebut dengan server inferensi yang digunakan. Jangan pernah menyimpan kunci API dalam bentuk teks, screenshot, atau string kueri. Biarkan kolom kunci API kosong saat mengedit saluran yang sudah ada, agar kunci yang disimpan tetap terjaga. Gunakan koneksi tanpa kunci hanya jika layanan tersebut memungkinkannya.

## Pengaturan default yang disesuaikan berdasarkan lingkungan sekitar

Profil yang disertakan dalam OpenAI dapat dikonfigurasi sebelum aplikasi dijalankan, menggunakan nilai-nilai seperti `LOCAL_SHELL_MCP_MODEL_BASE_URL` (atau `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL`, dan `LOCAL_SHELL_MCP_MODEL_API_KEY` (atau `OPENAI_API_KEY`). Profil yang disertakan dalam Anthropic dan Google dapat membaca nilai-nilai seperti `ANTHROPIC_API_KEY` dan `GOOGLE_KEY`/`GOOGLE_API_KEY`. Profil yang disimpan akan memiliki prioritas lebih tinggi dibandingkan alternatif yang dihasilkan oleh lingkungan tempat aplikasi berjalan. Gunakan saluran-saluran yang memiliki nama tertentu untuk menangani beberapa endpoint yang independen. Pengaturan default yang disesuaikan oleh lingkungan bukanlah alternatif untuk melindungi rahasia layanan tersebut.

## Autentikasi akun ChatGPT

Kanal/Codex menggunakan proses otentikasi yang berbasis pada akun ChatGPT yang didukung, bukan kunci API biasa. Proses otentikasi dapat dilakukan melalui pengelolaan kanal tersebut, dan login dilakukan di halaman otentikasi resmi. Dalam konteks penyebaran lokal, proses callback dapat dilakukan secara otomatis. Jika browser tidak dapat terhubung ke listener yang digunakan untuk proses otentikasi, maka URL callback tersebut perlu dikopykan dari bar alamat browser dan dimasukkan ke dalam dialog otentikasi. Kegagalan koneksi di alamat loopback merupakan hal yang wajar dalam proses otentikasi ini.

Perlakukan URL callback sebagai kredensial: jangan pernah mengirimkannya di chat atau memublikasikannya. Controller menyimpan otorisasi di server dan memperbarui kredensial jika memungkinkan. Lakukan otorisasi ulang jika akun kedaluwarsa atau akses dicabut. Model yang tersedia, batas paket, dan penggunaan yang diizinkan ditentukan layanan akun hulu; LSM tidak menyediakan kuota langganan tambahan.

## Penemuan model dan batasan konteks

Aktifkan mekanisme penemuan otomatis untuk meminta informasi model dari penyedia layanan tersebut. Controller memperbarui informasi tersebut secara berkala (saat ini setiap sepuluh menit). Pengaturan manual juga tersedia. Jika penemuan model gagal, data model yang telah disimpan sebelumnya tetap akan dipertahankan. Jika penyedia layanan tidak memiliki endpoint yang sesuai untuk mengirimkan informasi model, maka aktivasi mekanisme penemuan harus dinonaktifkan, dan identifikasi model perlu dilakukan secara manual, satu per baris.

Tentukan nilai konteks untuk setiap model ketika model tersebut diketahui. Nilai yang ditentukan secara eksplisit akan menggantikan metadata yang ditemukan atau mengisi nilai yang hilang. Editor dapat menerima 1 hingga 2.000.000 token. Ini merupakan rentang konfigurasi, bukan jaminan bahwa penyedia layanan mendukung kapasitas tersebut. Gunakan batasan yang sesuai untuk deployment Anda, dengan memperhatikan konfigurasi server dan batasan model itu sendiri.

## Pengambilan sampel, proses penalaran, dan penggunaan

Konfigurasi default channel/model mengatur parameter permintaan yang didukung oleh penyedia layanan yang dipilih. Chat composer dapat menampilkan informasi mengenai proses penalaran jika tersedia. Protokol yang berbeda memiliki cara yang berbeda dalam melakukan pengambilan sampel dan proses penalaran. Sebuah opsi mungkin tidak didukung oleh model tertentu. Mulailah dengan konfigurasi default dari penyedia layanan, lalu ubah satu setting saja pada suatu waktu.

Organisasi non-pemerintah dapat meminta informasi mengenai penggunaan token streaming secara tepat. Organisasi tersebut juga dapat menggunakan alternatif lain jika penyedia layanan menolak opsi penggunaan tersebut. Endapan yang tidak mengembalikan informasi mengenai penggunaan layanan tidak dapat memberikan laporan pembayaran yang akurat atau statistik terkait cache. Lihat [Memory and context](context.md) untuk penjelasan mengenai perbedaan antara konsumsi total dan kapasitas kontekst saat ini.

## Mengubah dan menghapus kanal

Sebuah percakapan tetap mempertahankan model/Agent yang digunakan serta riwayat percakapan tersebut. Perubahan model tersebut perlu dilakukan secara sengaja, terutama ketika mengganti endpoint atau meng debugging masalah yang terjadi pada provider. Penyebutan saluran yang sedang digunakan juga dibatasi demi melindungi referensi yang ada. Pemutusan suatu saluran yang sedang digunakan memerlukan konfirmasi tambahan: riwayat percakapan tetap tersimpan, tetapi Agent dan chats yang merujuk pada saluran yang telah diputus harus memilih pengganti yang dapat bekerja dengan baik sebelum proses eksekusi dilanjutkan.

Pengaturan kanal tersebut berada di sisi server, bukan hanya berupa pengaturan yang tersimpan di browser saja. Kredensial tidak dikembalikan melalui respons biasa dari katalog kanal. Pastikan agar direktori state controller dan salinan data tersebut dilindungi dengan baik, karena kredensial tersebut disimpan dalam direktori tersebut.

## Checklist koneksi

1. Pastikan bahwa Controller dapat menjangkau host API tersebut, dan bahwa protokol TLS berfungsi dengan baik.
2. Pastikan path dasar, protokol, kredensial, dan ID model yang digunakan benar.
3. Perbarui informasi mengenai kanal tersebut, atau masukkan model yang diketahui secara manual.
4. Kirimkan prompt berupa teks sederhana, lalu uji pemanggilan alat kecil.
5. Periksa detail kesalahan yang terjadi, seperti status HTTP yang tidak valid, timeout, atau opsi yang tidak didukung. Jangan mencoba lagi menggunakan kredensial yang tidak valid.

Lihat [Administration and troubleshooting](administration.md) untuk menangani masalah terkait batasan kecepatan, gangguan streaming, dan kesalahan autorisasi.
