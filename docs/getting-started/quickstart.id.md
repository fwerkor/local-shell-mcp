<!-- i18n-source-sha256: 8c51015fb3cc5269af4d5bf07eddfa8deac64e90f0063ee8cd1fc661439f7679 -->
# Mulai cepat

Panduan ini memulai Pengontrol LSM dan membuka antarmuka browsernya. [unified web workspace](web-workspace.md) adalah pengalaman harian yang direkomendasikan; ini adalah tumpukan obrolan opsional yang diterapkan secara terpisah. ChatGPT, Gemini, dan klien MCP eksternal lainnya dapat terhubung ke Pengontrol yang sama. Lihat [runtime choices and deployment model](../guides/deployment.md).

## Persyaratan

- Docker Engine dengan Compose v2.
- Titik akhir HTTPS publik jika pengguna jarak jauh atau klien MCP eksternal harus terhubung.
- Direktori workspace khusus.
- OAuth admin PIN dan JWT secret acak yang panjang.

!!! warning
    Model yang terhubung dapat mengoperasikan workspace yang dikonfigurasi. Jalankan layanan dalam container atau VM yang dapat dibuang dan hindari mount resource pengendali host.

## 1. Clone dan konfigurasi

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

Edit `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. Mulai server

```bash
mkdir -p workspaces/default
docker compose up -d
```

Periksa status:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Respons yang sehat mengembalikan HTTP `200`.

## 3. Publikasikan HTTPS

Untuk sidecar Cloudflare Tunnel:

```bash
docker compose --profile tunnel up -d
```

Di Cloudflare Zero Trust, arahkan public hostname ke:

```text
http://local-shell-mcp:8765
```

Untuk Caddy, Nginx, Traefik, Nginx Proxy Manager, atau reverse proxy lain, teruskan traffic HTTPS ke `127.0.0.1:8765` atau alamat jaringan container.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Jika menggunakan profil tunnel:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
