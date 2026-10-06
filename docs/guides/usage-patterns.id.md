<!-- i18n-source-sha256: 2f0d76e5baf715634ab1bed49cb63a1382ae50536e2b8ebb880f3a27df3f8abc -->
# Pola penggunaan dan panduan prompting

`local-shell-mcp` menyediakan tools yang kuat. Hasil yang baik bergantung pada meminta model menginspeksi terlebih dahulu, bertindak dalam langkah kecil, melakukan verifikasi, dan melaporkan perubahan.

## Loop operasi umum

Gunakan loop ini untuk sebagian besar task coding:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read`, dan `run_shell` untuk command seperti `git status`.
2. Plan: minta model mengidentifikasi file dan tests minimal yang terlibat.
3. Edit: gunakan `file_edit`, `file_patch`, atau shell commands.
4. Verify: jalankan targeted tests/builds dengan `run_shell` atau persistent shells.
5. Review: jalankan `git diff` melalui `run_shell`, lalu gunakan `secret_scan` dan `audit_tail` bila diperlukan.
6. Commit/export: gunakan explicit Git CLI commands melalui `run_shell` atau `link_create`.

## Pemilihan tool

| Task | Utamakan | Hindari |
|---|---|---|
| One-shot command singkat | `run_shell` | Memulai persistent shell untuk setiap command |
| Dev server, REPL, atau watch task lama | `shell_start` + `shell_read` + `shell_send` | Memblokir `run_shell` sampai timeout |
| Structured analysis atau file generation | `run_python` | Shell pipeline rapuh untuk JSON/text kompleks |
| Edit exact kecil | `file_edit` | Menulis ulang file penuh tanpa perlu |
| Satu atau beberapa replacement dalam satu file | `file_edit` with an `edits` array | Mengulang stale edit tanpa membaca ulang |
| Multi-file patch | `file_patch` | Ad hoc shell edit |
| Mencari file | `file_tree`, `file_glob` | Recursive listing penuh pada repository besar |
| Mencari code | `file_grep` | Membaca banyak file secara buta |
| Browser evidence | `browser_snapshot`, `browser_run_script` | Menebak dari nama page/route |
| Downloadable artifacts | `link_create` | Menempel binary content besar ke chat |
| Remote machine work | normal tools with `machine`, plus `remote_transfer` | Membuka inbound SSH saat outbound worker sudah cukup |

## Memanggil tool dari CLI

Untuk shell script dan CI, `lsm call <tool>` memanggil permukaan tool terdaftar yang sama melalui loopback controller yang sedang berjalan, sehingga remote worker dan state controller tetap dipertahankan.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Gunakan `--session s_...` untuk mengaitkan panggilan dengan Logical Session. Pada setup Docker Compose yang didokumentasikan, `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN` mentah hanya berada di `.env` milik host yang izinnya dibatasi, sedangkan Compose hanya meneruskan verifier SHA-256 ke controller; layout runtime terpisah lainnya dapat memakai `--token-file <path>`. `--direct` melewati controller, menerapkan pengaturan runtime dari `.env` saat ini di dalam proses, tidak menyuntikkan token CLI host ke lingkungan tool, dan hanya berlaku untuk panggilan lokal.

## Template prompt

### Orientasi read-only repository

```text
Gunakan local-shell-mcp. Inspeksi layout repository dan git status. Jangan ubah file. Rangkum component utama, test command yang dapat disimpulkan, dan risk yang jelas sebelum membuat perubahan.
```

### Focused bug fix

```text
Gunakan local-shell-mcp untuk memperbaiki bug. Pertama reproduce atau locate dengan relevant command terkecil. Baca file sebelum edit. Buat minimal patch, jalankan targeted verification, lalu tampilkan git diff dan tests tepat yang dijalankan. Jangan commit sampai saya menyetujui.
```

### Workflow commit dan push

```text
Gunakan local-shell-mcp. Periksa git status dan diff, jalankan relevant tests dan secret_scan, buat satu focused commit dengan message ringkas, lalu push current branch. Jangan sertakan cache, build artifacts, atau unrelated formatting.
```

### Long-running process

```text
Mulai dev server dalam persistent shell session, baca output sampai ready, lalu gunakan browser tools untuk memverifikasi page. Simpan session id dan kill session setelah verifikasi.
```

### Remote worker task

```text
Gunakan remote worker terhubung bernama <machine>. Pertama panggil environment_get dengan machine=<machine>, lalu file_list dengan machine yang sama. Kerjakan hanya di configured remote workdir. Gunakan run_shell untuk command singkat dan shell_start atau job_start untuk pekerjaan lama.
```

## Bekerja dengan repositories

Sequence yang disarankan untuk perubahan open-source:

1. Jalankan `git status --short --branch` melalui `run_shell`.
2. Fetch dan inspect branches dengan explicit Git CLI saat upstream state penting.
3. Gunakan `file_grep` dan `file_read` sebelum edit.
4. Buat minimal patch.
5. Jalankan targeted tests dahulu, lalu broader tests jika praktis.
6. Jalankan `secret_scan` sebelum commit atau push.
7. Stage dan commit secara eksplisit dengan message ringkas.

Minta satu commit per logical change bila maintainer membutuhkan history yang mudah direview.

## Bekerja dengan generated artifacts

Untuk PDF, report, screenshot, archive, atau log:

1. Generate file di dalam workspace.
2. Verifikasi file ada dan ukurannya sesuai.
3. Gunakan `link_create` dengan TTL singkat dan optional `max_downloads`.
4. Revoke link ketika tidak lagi dibutuhkan.

Jangan buat public link untuk private key, credential directory, atau unrelated personal data.

## Bekerja dengan remote machines

Remote worker mode berguna ketika machine bisa melakukan outbound HTTPS tetapi tidak bisa menerima inbound SSH.

Praktik baik:

- Buat atau rename machine dengan `remote_manage(action="invite", ...)` atau `remote_manage(action="rename", ...)`.
- Panggil `environment_get(machine=...)` sebelum bertindak.
- Gunakan `remote_transfer` untuk memulai controller/worker atau worker/worker transfer jobs, lalu kelola dengan normal `job_*` tools.
- Revoke worker setelah task dengan `remote_manage(action="revoke", ...)`.

## Anti-patterns

Hindari instruksi ini kecuali environment disposable dan konsekuensinya dipahami:

- “Install apa pun yang diperlukan secara global” pada host-launched server.
- “Jalankan sampai berhasil” tanpa time bound atau verification criteria.
- “Commit semuanya” pada repository dengan generated artifacts.
- “Expose seluruh home directory” demi kenyamanan.
- “Buat file link untuk seluruh workspace”.
- Menjalankan public deployment dengan `LOCAL_SHELL_MCP_AUTH_MODE=none`.
