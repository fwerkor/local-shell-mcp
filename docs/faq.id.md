# Pertanyaan umum

Halaman ini membahas masalah Client dan reverse proxy yang sering terjadi dan dapat terlihat seperti kegagalan LSM meskipun server sebenarnya sehat.

## Mengapa beberapa alat tidak tersedia di ChatGPT setelah LSM ditingkatkan?

### Gejala

- Alat baru tidak muncul di ChatGPT.
- ChatGPT masih mencoba memanggil alat lama yang dihapus, diganti nama, atau digabungkan.
- Alat tersedia, tetapi panggilan gagal karena ChatGPT mengirim skema input lama.
- Memulai ulang LSM atau membuka percakapan baru tidak menyelesaikan masalah.

### Penyebab

ChatGPT dapat menyimpan snapshot tetap dari alat dan skema input yang tersedia saat MCP App dipindai, disetujui, atau diterbitkan. Saat rilis LSM mengubah `tools/list`, snapshot tersebut tidak dijamin diperbarui secara otomatis. Ini bukan cache singkat dengan waktu kedaluwarsa yang terdokumentasi.

### Solusi

=== "Mode pengembang atau koneksi pribadi"

    1. Buka **ChatGPT Settings → Apps**.
    2. Buka LSM App dan gunakan **Refresh** untuk memindai ulang alat.
    3. Jika Refresh tidak tersedia, hapus App lama dan tambahkan kembali endpoint MCP yang sama.
    4. Mulai percakapan baru setelah daftar alat terbaru diterima.

=== "App yang diterbitkan di ChatGPT Business"

    App kustom yang sudah diterbitkan saat ini tidak dapat memperbarui alat atau metadata secara langsung. Administrator harus membuat App baru, memindai endpoint LSM saat ini, menerbitkan penggantinya, lalu menghentikan App lama.

=== "ChatGPT Enterprise atau Edu"

    Administrator dapat membuka **Workspace Settings → Apps → LSM App → … → Action control → Refresh**, meninjau perbedaan, dan mengaktifkan action baru bila diperlukan.

Lihat [issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) dan [dokumentasi MCP App OpenAI](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## Mengapa WebUI terus menyambung ulang di belakang Nginx?

### Gejala

- Halaman WebUI dan login OAuth dimuat normal.
- TUI tidak pernah muncul.
- Status terus berubah antara `Connecting`, `Connection error`, dan `Reconnecting`.
- Koneksi langsung ke port `8765` berfungsi.

### Penyebab

Antarmuka browser merender TUI asli melalui PTY WebSocket. Endpoint default adalah `/ui/ws`; dengan `ui_path` kustom, endpoint menjadi `${ui_path}/ws`. `proxy_pass` Nginx biasa tidak otomatis meneruskan header hop-by-hop yang diperlukan untuk upgrade WebSocket.

### Solusi

Aktifkan HTTP/1.1 dan teruskan header `Upgrade` serta `Connection`:

```nginx
# Letakkan map di blok http.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

Validasi lalu muat ulang Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Di Nginx Proxy Manager, aktifkan **Websockets Support** pada Proxy Host. Jika masih menyambung ulang, tambahkan header upgrade yang setara di Advanced.

### Verifikasi

Buka alat pengembang browser, muat ulang WebUI, dan periksa permintaan `/ui/ws`. Koneksi yang benar mengembalikan:

```text
101 Switching Protocols
```

Lihat [issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
