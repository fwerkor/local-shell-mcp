<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# Konektivitas jaringan

MCP client HTTP di luar mesin memerlukan HTTPS origin yang dapat dijangkau. Halaman ini membahas routing jaringan, bukan pemilihan runtime.

client endpoint biasanya berakhir dengan `/mcp`:

```text
https://your-public-host.example.com/mcp
```

Pengaturan public base URL server hanya berisi origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Jangan sertakan `/mcp` dalam base URL tersebut.

## Opsi konektivitas

**Direkomendasikan:** Untuk akses publik, gunakan server publik atau teruskan lalu lintas melalui server publik dengan reverse proxy HTTPS.

**Tidak direkomendasikan:** Kecepatan unggah sisi klien Cloudflare Tunnel bisa sangat lambat, sehingga fitur unggah dan transfer berkas sulit digunakan. Gunakan hanya jika server publik atau penerusan tidak memungkinkan.


| Opsi | Kapan digunakan |
|---|---|
| Caddy | TLS otomatis yang sederhana |
| Nginx atau Nginx Proxy Manager | Infrastruktur Nginx yang sudah ada |
| Traefik | Routing container-native yang sudah ada |
| Penerusan lewat server publik | Untuk akses publik, gunakan server publik atau teruskan lalu lintas melalui server publik dengan reverse proxy HTTPS. |
| Cloudflare Tunnel (tidak direkomendasikan) | Teruskan lewat server publik; Cloudflare Tunnel hanya pilihan terakhir |

## Path

Teruskan seluruh origin ke server yang sedang berjalan. Path penting meliputi:

| Path | Tujuan |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Pemeriksaan kesehatan |
| `/.well-known/...` | Metadata discovery client |
| `/oauth/...` | Alur otorisasi client |
| `/downloads/...` | Tautan file hasil generasi opsional |
| `/join/...`, `/remote/...` | Alur remote-worker opsional |

## Perilaku proxy

Proxy harus mempertahankan path, meneruskan request body, mendukung response yang panjang, dan menghindari timeout yang terlalu singkat.

## Pemeriksaan

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Kesalahan umum

| Kesalahan | Perbaikan |
|---|---|
| Menggunakan `https://host` alih-alih `https://host/mcp` di ChatGPT | Tambahkan `/mcp` hanya pada client endpoint |
| Mengatur `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | Atur hanya origin |
| Hanya merutekan `/mcp` | Rute seluruh origin agar discovery dan otorisasi juga berfungsi |
| Menjalankan host runtime dengan workspace terlalu luas | Gunakan workspace sempit atau Docker |

## Pasangan yang disarankan

| Runtime | Pola jaringan |
|---|---|
| Docker Compose di server | Reverse proxy HTTPS |
| Docker Compose di mesin rumah | Teruskan lewat server publik; Cloudflare Tunnel hanya pilihan terakhir |
| VS Code extension di laptop | Penerusan lewat server publik |
| Binary di VM | Reverse proxy di VM atau edge jaringan |
| Server dev Python/source | Biasanya hanya localhost |
| Stdio mode | Tidak ada jalur HTTP; gunakan MCP client lokal |
