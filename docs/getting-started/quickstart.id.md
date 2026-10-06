<!-- i18n-source-sha256: 81fe33aa286565e6436467d117cc77d94ec91671e33e559a6bb888223d0c8bc1 -->
# Mulai cepat

Panduan ini memakai Docker Compose sebagai runtime pertama dan ChatGPT sebagai client pertama. Keduanya adalah pilihan terpisah: Docker, VS Code extension, binary, Python, dan stdio adalah opsi runtime; ChatGPT dan client MCP generik adalah opsi client. Lihat [pilihan runtime dan model deployment](../guides/deployment.md) untuk gambaran lengkap.

## Persyaratan

- Docker Engine dengan Compose v2.
- Endpoint HTTPS publik jika ChatGPT harus terhubung dari Web.
- Direktori workspace khusus.
- OAuth admin PIN dan JWT secret acak yang panjang.

!!! warning
    Model yang terhubung dapat mengoperasikan workspace yang dikonfigurasi. Jalankan layanan dalam container atau VM yang dapat dibuang dan hindari mount resource pengendali host.

## 1. Clone dan konfigurasi

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import hashlib,secrets; p=Path(".env"); s=p.read_text(); t=secrets.token_urlsafe(48); s=s.replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=" + t, 1).replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=" + hashlib.sha256(t.encode()).hexdigest(), 1); p.write_text(s)'
chmod 600 .env
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

## 4. Hubungkan ChatGPT

Gunakan endpoint MCP:

```text
https://your-public-host.example.com/mcp
```

Ikuti [panduan konektor ChatGPT](chatgpt-connector.md) untuk menyelesaikan OAuth dan persetujuan tools.

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
| Tambahkan ChatGPT sebagai client | [ChatGPT connector](chatgpt-connector.md) |
| Pilih tools dan tulis prompt lebih baik | [Pola penggunaan](../guides/usage-patterns.md) |
| Hubungkan mesin HPC, NPU/GPU, atau NAT | [Worker jarak jauh](../guides/remote-workers.md) |
| Pahami semua tools MCP | [Referensi tools](../reference/tools.md) |
