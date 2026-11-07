<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# Mulai cepat

Panduan ini memulai Pengontrol LSM dan membuka antarmuka browsernya. [unified web workspace](web-workspace.md) adalah pengalaman harian yang direkomendasikan; ini adalah tumpukan obrolan opsional yang diterapkan secara terpisah. ChatGPT, Gemini, dan klien MCP eksternal lainnya dapat terhubung ke Pengontrol yang sama. Lihat [runtime choices and deployment model](../guides/deployment.md).

Metode yang direkomendasikan adalah **deploy langsung dari source checkout** dalam lingkungan terisolasi. Docker Compose adalah alternatif.

## Persyaratan

- Git dan Python 3.11+ dengan `venv` serta `pip`.
- HTTPS publik hanya bila pengguna jarak jauh atau klien MCP eksternal perlu akses.
- Direktori workspace khusus dengan izin terbatas.
- PIN admin OAuth kuat dan secret JWT acak.

!!! warning
    Model yang terhubung dapat mengoperasikan workspace yang dikonfigurasi. Jalankan layanan dalam container atau VM yang dapat dibuang dan hindari mount resource pengendali host.

## 1. Clone dan konfigurasi

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

Edit `.env` dan ganti contoh PIN serta JWT secret (pakai `openssl rand -hex 32`). Runtime source tidak memuat `.env` secara otomatis.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Mulai server

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Periksa status dari terminal lain:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Respons sehat adalah HTTP `200`. Gunakan pengelola layanan untuk proses permanen.

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

Perbarui source, instal ulang paket editable, lalu restart Controller:

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

Jika memakai Docker Compose, perbarui kontainer:

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
