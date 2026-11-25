<!-- i18n-source-sha256: 2fb1887d3d0f7ca8ac19f19375829b9269f666b08197e4915c0230669303c8fe -->
# Pencarian web dan pembacaan dokumen di WebUI

Pencarian web aktif secara bawaan dalam
obrolan WebUI. Anda dapat menonaktifkannya
untuk setiap percakapan melalui tombol di
bawah kotak pesan; pilihan itu disimpan
bersama percakapan. Tidak diperlukan kunci
API penyedia atau izin shell Worker.

Agent hanya menerima dua alat baca.
`web_search(query)` mengembalikan judul, URL,
dan cuplikan hasil pencarian publik. Alat ini
memakai `ddgs` jika tersedia, atau mencoba
Bing RSS tanpa kunci. Layanan publik dapat
membatasi permintaan atau gagal merespons.

`web_fetch(url, query?, offset?, limit?)`
membaca HTML, teks biasa, JSON, XML,
Markdown, dan PDF. Untuk halaman abstrak
arXiv, alat ini mencoba teks lengkap HTML
terlebih dahulu, lalu PDF jika tidak
tersedia. Tidak diperlukan API khusus makalah
ilmiah.

Pada pembacaan pertama, teks lengkap disimpan
dalam cache pribadi Controller bila direktori
dapat ditulis. Cache dipisahkan per pengguna,
kedaluwarsa setelah 24 jam, dan dibatasi 80
berkas per pengguna. Hasil biasa maksimal
8000 karakter; pencarian, offset, dan batas
dapat dipakai untuk melanjutkan hingga 12000
karakter per panggilan.

Unduhan dibatasi 20 MiB dan teks yang
diekstrak 3 MiB. Alamat jaringan privat,
kredensial dalam URL, port tidak standar, dan
pengalihan berbahaya ditolak. Koneksi hanya
dibuat ke IP publik tervalidasi untuk
mencegah DNS rebinding.

PDF diproses dengan PyMuPDF dan cadangan
`pypdf`. Dokumen pindaian tanpa lapisan teks
membutuhkan OCR dan menghasilkan galat yang
jelas. Pengodean karakter HTML yang
dinyatakan digunakan dan format yang tidak
didukung ditolak.

Tautan hasil ditampilkan dalam kartu keluaran
alat. Jawaban sebaiknya menyebut URL asli dan
nomor halaman PDF bila memungkinkan. Konten
eksternal tidak dapat dipercaya dan
instruksinya tidak boleh mengganti perintah
pengguna atau pengaturan Agent.

Halaman HTML kosong atau bergantung pada JavaScript dicoba ulang dalam konteks
Chromium headless baru jika ekstra browser opsional dan Chromium terpasang.
Halaman statis dan PDF tidak membuka browser. Rendering memakai transport HTTP
yang sama, terbatas pada IP publik, memblokir permintaan selain baca dan jaringan
langsung browser, dengan batas 25 detik dan 128 permintaan.
Halaman yang membutuhkan login, CAPTCHA, atau pengalihan yang tidak didukung mungkin gagal.
Penolakan akses dan hasil kosong dilaporkan, bukan disimpan dalam cache.
