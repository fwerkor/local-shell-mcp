<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# Ruang kerja web terpadu

**Ruang kerja web LSM terpadu** adalah cara yang disarankan untuk menggunakan local-shell-mcp sehari-hari. Ini menggabungkan obrolan AI, riwayat proyek, dan bidang kendali LSM dalam satu antarmuka responsif, berdasarkan antarmuka LibreChat yang dimodifikasi dan dibuat oleh vendor. Anda masih dapat menghubungkan klien MCP eksternal seperti [ChatGPT](chatgpt-connector.md) atau [Gemini](gemini-spark.md).

Ruang kerja **dihosting sendiri dan opsional untuk dipasang**: ini adalah layanan web terpisah, bukan bagian dari gambar Pengontrol minimal, paket Pekerja jarak jauh yang dapat dijalankan secara mandiri atau jarak jauh. Penerapan khusus pengontrol mempertahankan UI browser asli dan OpenTUI.

## Apa yang ada di ruang kerja?

| Daerah | Apa yang bisa Anda lakukan |
|---|---|
| Obrolan dan proyek | Pilih model yang dikonfigurasi, buat percakapan, atur proyek, temukan obrolan sebelumnya, dan arsipkan percakapan. Riwayat tetap ada di server. |
| Ikhtisar pengontrol | Lihat kesehatan, aktivitas terkini, dan mesin yang terhubung. |
| File | Telusuri dan kelola file lokal atau jarak jauh. |
| Terminal | Bekerja dengan terminal persisten pada Pengendali atau Pekerja. |
| Desktop | Periksa dan kendalikan sesi GUI jarak jauh. |
| Sesi | Periksa tugas LSM yang tahan lama dan siklus hidupnya. |
| Remote | Hubungkan dan kelola Pekerja keluar. |
| Audit | Periksa aktivitas alat yang berasal dari model. |
| MCP Bersarang | Daftarkan, edit, aktifkan, nonaktifkan, segarkan, dan hapus server MCP eksternal di belakang LSM. |

Rute Pengontrol adalah `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` dan `/control/audit`. Obrolan dibuka di `/c/new`. Manajer MCP LSM mengontrol **registrasi MCP bertingkat LSM**; itu tidak membuat registri kedua di LibreChat.

## Terapkan tumpukan obrolan opsional

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## Masuk dan gunakan obrolan

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Unggahan obrolan (hingga 32 MiB) disimpan di ruang kerja Pengontrol dan jalur absolutnya diberikan ke model. Unggahan browser tidak memberikan izin file tambahan. Panggilan alat yang menghadap model melewati otorisasi LSM, audit, dan router pekerja jarak jauh.

## MCP eksternal, keamanan dan data

Gunakan sidebar MCP ruang kerja untuk mengelola server MCP eksternal bertumpuk. Ini mendukung server stdio lokal dan server HTTP, termasuk variabel lingkungan pribadi terpisah dan header permintaan. Rahasia tidak dikembalikan ke browser. Tombol obrolan **MCP Eksternal** memungkinkan penelusuran, inspeksi, dan pemanggilan alat yang disarangkan; itu tidak memberikan model `mcp_manage` ketika alat LSM asli dinonaktifkan. Manajemen UI dilindungi oleh otorisasi Pengontrol normal.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Pemecahan masalah

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Untuk detail implementasi dan pembaruan, lihat [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) dan [human interface guide](../guides/human-interface.md).
