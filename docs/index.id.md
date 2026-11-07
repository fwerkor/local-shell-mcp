<!-- i18n-source-sha256: 276e9356b895a85759d31467512bdc530c9baa216a368df4ef1bccce39530d0e -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">Ruang kerja AI yang dihosting sendiri · Bidang kendali MCP</span>

# local-shell-mcp

Obrolan, proyek, file, terminal, mesin jarak jauh, dan alat AI dalam satu antarmuka yang dihosting sendiri. Hubungkan klien MCP eksternal saat Anda membutuhkannya.

<div class="hero-actions" markdown>
[Mulai](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Referensi tools](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Lingkungan coding nyata
Jalankan tests, inspeksi repositories, patch files, operasikan Git, dan simpan audit trail dari satu MCP endpoint.
</div>

<div class="feature-card" markdown>
### Ruang kerja web terpadu
Gunakan obrolan bawaan dan riwayat proyek bersama file Pengontrol, terminal, desktop, sesi, remote, dan audit. Klien MCP eksternal tetap opsional.
</div>

<div class="feature-card" markdown>
### Kontrol remote machine
Hubungkan mesin di balik NAT, firewall, atau HPC melalui outbound worker connections tanpa membuka port SSH.
</div>
</div>

## Yang disediakan

`local-shell-mcp` menyediakan ruang kerja AI terpadu yang dihosting sendiri dan server MCP untuk klien eksternal. Ini menyediakan shell, shell persisten, sistem file, pencarian, patch, Git, Playwright, audit, sesi logis yang tahan lama dengan rencana Sasaran opsional, tautan file yang diberi token, dan alat pekerja jarak jauh melalui titik akhir MCP yang diautentikasi.

Gunakan saat AI perlu inspeksi repository, menjalankan tests, mengedit files, mengoperasikan Git, mengumpulkan browser evidence, membuat downloadable artifacts, atau mengontrol remote machine yang hanya dapat terhubung outbound ke control server.

## Arsitektur

```text
Lapisan runtime: Docker / VS Code extension / binary / Python / stdio
Lapisan exposure: localhost / HTTPS proxy / tunnel / stdio pipe
Lapisan klien: WebUI/Gemini/ChatGPT/klien MCP generik terpadu
Workspace terkontrol: /workspace or configured workspace root
Remote workers opsional: outbound machine connections
```

Isolation boundary yang dimaksud adalah container atau VM tempat service berjalan.

## Mulai berdasarkan skenario

| Skenario | Mulai di sini | Alasan |
|---|---|---|
| Ruang kerja browser utama | [Unified web workspace](getting-started/web-workspace.md) | Obrolan, proyek, dan halaman kontrol LSM dengan login bersama |
| Penerapan Pengendali pertama | [Quickstart](getting-started/quickstart.md) | Source checkout yang direkomendasikan, OAuth dan sesi browser pertama. |
| Memilih runtime layer | [Runtime choices](guides/deployment.md) | Menjelaskan Docker, VS Code, binary, Python, dan stdio sebagai opsi runtime terpisah |
| Menghubungkan Percikan Gemini | [Gemini Custom Apps](getting-started/gemini-spark.md) | Kelayakan, URL HTTPS MCP, OAuth, dan pengujian |
| Menambahkan ChatGPT sebagai client | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, prompt aman pertama, tool discovery |
| Menambahkan LSM ke DeepSeek Harness | [Plugin DeepSeek Harness](clients/deepseek-harness.md) | Instal repository ini sebagai bundle DSH sambil mempertahankan seluruh tool dan remote-worker surface LSM |
| Menjalankan dari VS Code | [VS Code extension runtime](installation/vscode-extension.md) | Runtime yang diluncurkan editor dan catatan keamanan host |
| Belajar mengoperasikan toolset | [Usage patterns](guides/usage-patterns.md) | Template prompt dan panduan pemilihan tools |
| Memahami setiap tool | [Tools reference](reference/tools.md) | Purpose, inputs, returns, combinations, dan notes untuk setiap tool |
| Menghubungkan HPC, NPU/GPU, atau server node | [Remote workers](guides/remote-workers.md) | Outbound worker join flow dan remote tool usage |
| Membagikan file yang dihasilkan | [File links](guides/file-links.md) | Tokenized download URL dengan TTL dan revocation |
| Mengeraskan deployment | [Security](security.md) | Isolation, OAuth, workspace scope, dan audit logs |

## Family tools utama

| Family | Contoh | Penggunaan |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, tests, scripts, long-running processes |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository inspection dan precise edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Reviewable source-control workflows |
| Sessions dan goals | `session_manage`, `plan_manage` | Durable task handoff, progress report, dan optional Goal mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistent interaction, UI checks, screenshots, rendered docs, dan page text |
| File links | `link_create`, `link_revoke` | Download generated artifacts dari chat |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | Machines di balik NAT, firewalls, atau cluster login flows |

## Workflow umum

### Pengkodean di ruang kerja web

1. Mulai Pengontrol LSM dan [unified web workspace](getting-started/web-workspace.md) opsional.
2. Buka `/ui` dan masuk menggunakan identitas LSM.
3. Konfigurasikan titik akhir model dan buka percakapan baru.
4. Minta model untuk memeriksa repositori dan menjalankan pemeriksaan hanya-baca terlebih dahulu.
5. Setelah disetujui, izinkan patch files, tests, diff review, commit, dan push.
6. Review audit log saat task melibatkan file links atau remote systems.

### Remote HPC atau accelerator host

1. Buat one-time remote worker invite.
2. Tempel generated command pada remote host.
3. Gunakan normal tools dengan `machine`; Git melalui `run_shell` dan transfer melalui `remote_transfer`.
4. Revoke worker setelah task.

### Artifact generation

1. Biarkan AI generate file di bawah `/workspace`.
2. Buat tokenized file link dengan TTL/download limits.
3. Bagikan link di chat.
4. Revoke setelah selesai.

## Bahasa

Site ini dibangun dengan native MkDocs i18n plugin. Gunakan language selector di header untuk berganti antara English dan translated pages. Page tanpa translation fallback ke English.
