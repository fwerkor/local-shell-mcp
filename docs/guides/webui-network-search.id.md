<!-- i18n-source-sha256: 78ec7a5b5dc75473db69b12cf1626f81c3071f52661bf1023047af5d6d24e3ee -->
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
