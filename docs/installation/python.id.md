<!-- i18n-source-sha256: c8c0d8ebdbb123b9ac4af1fd288f30e8ca69037ca086486cb8027e2592f4b75a -->
# Runtime Python, pipx, dan source

**Instalasi langsung dari repository sumber direkomendasikan.** Pakai Python virtual environment dan workspace terbatas; Docker Compose tetap tersedia.

Gunakan halaman ini untuk tiga kasus terkait:

- `pipx install local-shell-mcp`: instalasi executable tingkat pengguna.
- `pip install local-shell-mcp`: instalasi ke virtual environment yang sudah ada.
- Editable source checkout: mengembangkan atau men-debug project itu sendiri.

## Instalasi pipx

`pipx` adalah instalasi berbasis Python paling bersih bagi pengguna biasa karena memberikan virtual environment tersendiri untuk command sekaligus mengekspos executable di `PATH`.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Mulai server MCP HTTP lokal:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Periksa kesehatan:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Instalasi virtual environment

Gunakan jika Anda sudah mengelola lingkungan Python secara manual:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

Process menggunakan tool yang terpasang di host. Paket Python tidak memasang compiler, Git, browser system dependency, atau project dependency untuk Anda.

## Editable source checkout

Gunakan untuk deployment biasa dan pengembangan. Untuk akses publik, lihat [quickstart](../getting-started/quickstart.md).

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Replace the example OAuth secrets in .env before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Jalankan pemeriksaan:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Penyiapan browser

Playwright bersifat opsional; instal library dan browser hanya saat diperlukan.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

Instalasi browser bersifat opsional; image Docker dasar tidak menyertakan Playwright atau browser.

## Penggunaan HTTP MCP publik

Untuk ChatGPT atau public HTTP MCP client lain, konfigurasikan public-origin dan OAuth yang sama dengan runtime HTTP lainnya, lalu ekspos port lokal melalui reverse proxy atau tunnel.

Endpoint MCP publik:

```text
https://your-public-host.example.com/mcp
```

## Mode pengembangan

| Mode | Command | Penggunaan |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | MCP client lengkap melalui HTTP, termasuk ChatGPT di balik HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Endpoint diagnostik atau kompatibilitas, bukan jalur utama ChatGPT |
| stdio | `local-shell-mcp --mode stdio` | MCP client lokal yang menjalankan process |

`mode=both` dicadangkan dan saat ini tidak boleh digunakan sebagai mode satu process.

## Keamanan host runtime

Instalasi Python berjalan sebagai host user kecuali ditempatkan di VM/container. Batasi workspace, biarkan full-container mode nonaktif, dan jangan arahkan workspace ke home directory.

Gunakan Docker Compose untuk repository yang tidak dipercaya, task yang banyak memakai package manager, atau workflow ketika resetability lebih penting daripada integrasi host.
