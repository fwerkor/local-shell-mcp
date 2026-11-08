<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Mulai cepat

Panduan ini memulai Pengontrol LSM dan membuka antarmuka browsernya. [unified web workspace](web-workspace.md) adalah pengalaman harian yang direkomendasikan; ini adalah tumpukan obrolan opsional yang diterapkan secara terpisah. ChatGPT, Gemini, dan klien MCP eksternal lainnya dapat terhubung ke Pengontrol yang sama. Lihat [runtime choices and deployment model](../guides/deployment.md).

Direkomendasikan **satu berkas executable Controller** dari [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest) tanpa Python, Docker atau checkout source. Contoh **Linux x86_64**; platform lain: [panduan binary](../installation/binary.md).

## Persyaratan

- Executable sesuai platform dan `curl` (contoh Linux x86_64).
- HTTPS publik hanya jika pengguna jarak jauh atau klien MCP eksternal membutuhkannya.
- Workspace khusus dengan izin terbatas.
- PIN admin OAuth kuat dan secret JWT acak.

!!! warning
    Model yang terhubung dapat mengoperasikan workspace yang dikonfigurasi. Jalankan layanan dalam container atau VM yang dapat dibuang dan hindari mount resource pengendali host.

## 1. Unduh executable dan konfigurasi

Unduh executable satu berkas dan buat secret JWT:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

Buat `.env` dan ganti contoh PIN dan secret JWT (gunakan `openssl rand -hex 32`). Binary **tidak memuat** `.env` secara otomatis.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Mulai server

Jalankan executable secara langsung:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Periksa status dari terminal lain:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Respons sehat adalah HTTP `200`. Gunakan supervisor layanan dan akun terbatas untuk produksi.

## 3. Publikasikan HTTPS

Untuk akses jarak jauh gunakan server publik atau reverse proxy HTTPS (Caddy, Nginx, Traefik), arahkan seluruh origin termasuk transfer file ke:

```text
http://127.0.0.1:8765
```

Periksa HTTPS:

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel tidak direkomendasikan** untuk transfer file karena upload dari klien dapat lambat. Utamakan server publik atau proxy/forwarding biasa dengan OAuth tetap aktif. Alternatif: [Docker](../installation/docker.md).

## 4. Buka ruang kerja browser

Buka login Pengontrol:

```text
https://host-publik-anda.example.com/ui
```

Untuk obrolan, proyek, dan halaman kontrol terintegrasi, ikuti [unified web workspace guide](web-workspace.md). WebUI ringan asli tersedia saat obrolan tidak diinstal.

## 5. Konfirmasi akses tools dengan aman

Minta model:

```text
Gunakan local-shell-mcp. Pertama panggil environment_get, lalu daftar root workspace. Jangan ubah file dulu.
```

Tools read-only yang diharapkan:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Mulai dengan task coding yang dibatasi

Task pertama yang baik:

```text
Periksa repository ini, rangkum layout project, jalankan test suite yang ada jika jelas, dan jangan mengubah file.
```

Setelah konektivitas dikonfirmasi, berikan instruksi yang lebih spesifik:

```text
Perbaiki test yang gagal. Baca file terkait terlebih dahulu, buat patch sekecil mungkin, jalankan test target, lalu tampilkan git diff. Jangan commit sampai saya menyetujui.
```

## Pembaruan

Ganti executable lalu restart Controller:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Docker Compose diperbarui lewat kontainer; source: [Python](../installation/python.md).

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## Halaman berikutnya

| Kebutuhan | Halaman |
|---|---|
| Memahami pilihan runtime dan client | [Pilihan runtime dan model deployment](../guides/deployment.md) |
| Jalankan dengan Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Jalankan dari VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Jalankan dengan binary release | [Runtime binary mandiri](../installation/binary.md) |
| Jalankan dengan Python atau source checkout | [Python runtimes](../installation/python.md) |
| Gunakan antarmuka obrolan dan kontrol terpadu | [Unified web workspace](web-workspace.md) |
| Tambahkan Gemini Spark sebagai klien | [Gemini Custom Apps](gemini-spark.md) |
| Tambahkan ChatGPT sebagai client | [ChatGPT connector](chatgpt-connector.md) |
| Pilih tools dan tulis prompt lebih baik | [Pola penggunaan](../guides/usage-patterns.md) |
| Hubungkan mesin HPC, NPU/GPU, atau NAT | [Worker jarak jauh](../guides/remote-workers.md) |
| Pahami semua tools MCP | [Referensi tools](../reference/tools.md) |
