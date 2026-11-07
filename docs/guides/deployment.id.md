<!-- i18n-source-sha256: d699e8855ee01b72db68087e8a5d8f3957c702641e7e6956f268604b8b1f9d2b -->
# Pilihan runtime dan model deployment

`local-shell-mcp` memiliki dua keputusan yang saling melengkapi:

1. **Runtime**: bagaimana proses server berjalan dan workspace apa yang dikontrol.
2. **Antarmuka**: gunakan [unified web workspace](../getting-started/web-workspace.md) opsional, atau sambungkan klien MCP eksternal seperti Gemini atau ChatGPT.

Antarmuka harian yang direkomendasikan adalah ruang kerja web yang dihosting sendiri (obrolan, proyek, dan halaman kontrol LSM). Itu dikerahkan secara terpisah dari Pengendali. Docker, ekstensi VS Code, binari rilis, instalasi Python, dan mode stdio adalah cara untuk menjalankan Controller; aplikasi obrolan eksternal tetap menjadi klien opsional.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Tulis HTTP lokal saja Ruang kerja web terpadu
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Pengaturan umum yang dihosting sendiri adalah:

```text
Browser -> https://chat.example.com (ruang kerja web terpadu)
        -> Pengontrol shell-mcp lokal yang diautentikasi
        -> ruang kerja terkontrol dan Pekerja keluar
Klien eksternal opsional -> https://mcp.example.com/mcp
```

Setup MCP client lokal bisa lebih sederhana:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

**Direkomendasikan:** Untuk akses publik, gunakan server publik atau teruskan lalu lintas melalui server publik dengan reverse proxy HTTPS. **Tidak direkomendasikan:** Kecepatan unggah sisi klien Cloudflare Tunnel bisa sangat lambat, sehingga fitur unggah dan transfer berkas sulit digunakan. Gunakan hanya jika server publik atau penerusan tidak memungkinkan. ([Public HTTPS exposure](../clients/connectivity.md))

## Matriks pilihan runtime

| Waktu proses | Terbaik untuk | Batas isolasi | Sumber rantai alat | Akses MCP eksternal | Halaman |
|---|---|---|---|---|---|
| Penulisan Docker | Sebagian besar beban kerja agen pengkodean dan ruang kerja yang dapat diulang | Wadah | Gambar Pengontrol Ramping; instal rantai alat khusus tugas secara terpisah | Tambahkan proksi atau terowongan HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + sespan terowongan | Tidak direkomendasikan: Teruskan lewat server publik; Cloudflare Tunnel hanya pilihan terakhir | Wadah | Gambar proyek | Teruskan lewat server publik; Cloudflare Tunnel hanya pilihan terakhir | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Start/stop server dari editor workspace | Biasanya host process | Host tools plus executable yang dikonfigurasi | Tambahkan HTTPS tunnel/proxy eksternal untuk ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Host atau VM tanpa Docker | Host or VM | Host tools plus executable yang dikonfigurasi | Tambahkan HTTPS proxy atau tunnel | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Penggunaan Python-native, debugging, development | Host virtualenv or VM | Python package plus host tools | Tambahkan HTTPS proxy atau tunnel | [Python install](../installation/python.md) |
| Stdio mode | MCP client lokal yang spawn process langsung | Client process boundary | Host tools plus executable yang dikonfigurasi | Tidak dapat dipakai ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Matriks koneksi client

| Antarmuka | Membutuhkan HTTPS publik | Menggunakan `/mcp` | Membutuhkan OAuth | Waktu proses yang khas |
|---|---:|---:|---:|---|
| Ruang kerja web LSM terpadu | Ya untuk akses jarak jauh; proxy lokal juga dimungkinkan | Secara internal | login LSM | Pengontrol ditambah tumpukan web terpisah |
| Gemini Spark / Aplikasi Khusus | Ya | Ya | Ya untuk kepentingan umum | Pengontrol HTTP apa pun |
| ChatGPT custom MCP connector | Ya | Ya | Ya untuk penggunaan publik | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | Tidak | Tidak | Tidak | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Biasanya tidak di localhost; ya lintas jaringan | Ya | Disarankan di luar localhost | Any HTTP runtime |
| VS Code extension helper flow | Hanya jika ChatGPT harus connect | Ya saat copy URL ChatGPT | Disarankan untuk ChatGPT | VS Code-launched runtime |

Lihat [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md), dan [network connectivity](../clients/connectivity.md).

## Apa yang dikontrol tiap runtime

Setiap runtime menjalankan server code yang sama dan mengekspos family MCP tools yang sama ketika diaktifkan:

- Shell dan persistent shell sessions.
- Filesystem, search, dan patch tools.
- Git operations.
- Browser automation via Playwright.
- Audit log dan task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle dan machine-routed tools.

Perbedaannya bukan abstract API, melainkan **operating environment** di belakangnya.

| Pertanyaan | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Di mana command berjalan? | Di dalam container | Biasanya pada host workspace | Di host atau VM process environment |
| Default workspace? | Mounted `/workspace` | Folder VS Code saat ini atau path terkonfigurasi | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Apakah kompiler dan browser sudah diinstal sebelumnya? | TIDAK; menginstal apa yang dibutuhkan tugas tersebut | Hanya jika diinstal pada host | Hanya jika diinstal pada host |
| Mudah di-reset? | Buat ulang container dan workspace volume | Tergantung workspace | Tergantung host/VM |
| Cocok untuk arbitrary package install? | Ya jika disposable | Lebih berisiko di host | Lebih berisiko di luar VM |

## Pilihan yang disarankan

Gunakan **Docker Compose** terlebih dahulu kecuali Anda mempunyai alasan untuk tidak melakukannya. Ini memberikan batas keamanan yang jelas tanpa memerlukan toolchain pengembangan besar yang sudah diinstal sebelumnya.

Gunakan **ekstensi VS Code** saat alur kerja dimulai dari editor dan Anda menginginkan peluncur lokal. Ini masih waktu proses. Klien web jarak jauh memerlukan proxy atau terowongan HTTPS yang dapat dijangkau.

Gunakan **standalone binary** jika Docker tidak tersedia tetapi VM, container host, atau dedicated user account sudah memberi boundary.

Gunakan **`pipx` atau source install** untuk development/debugging `local-shell-mcp` atau jika Python-based environment lebih mudah dirawat.

Gunakan **stdio mode** hanya untuk MCP client lokal yang dapat spawn server process. Ini bukan public deployment dan tidak dapat dipakai langsung oleh ChatGPT web/app.

## Aturan public endpoint

Untuk klien HTTP MCP eksternal seperti Gemini dan ChatGPT, titik akhir MCP adalah:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` hanya origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Jangan tambahkan `/mcp` ke `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Halaman runtime

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Halaman client

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
