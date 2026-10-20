<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Remote worker

Remote worker memungkinkan `local-shell-mcp` mengontrol mesin yang dapat membuat permintaan HTTP(S) keluar tetapi tidak dapat menerima koneksi SSH masuk.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Workflow dasar

1. Buat undangan dengan `remote_manage(action="invite", ...)`.
2. Jalankan perintah yang dibuat di mesin remote.
3. Konfirmasikan pendaftaran dengan `remote_manage(action="list")`.
4. Panggil tool biasa dengan `machine="<worker-name>"`, misalnya `environment_get`, `run_shell`, `file_read`, atau `browser_run_script`.
5. Gunakan `remote_transfer` untuk memulai transfer file/direktori yang dilacak controller-to-worker, worker-to-controller, atau worker-to-worker. Ikuti dengan `job_list` atau `job_tail`; hentikan atau ulangi dengan `job_stop` atau `job_retry`.
6. Ubah nama atau cabut worker dengan `remote_manage(action="rename", ...)` atau `remote_manage(action="revoke", ...)`.

Hanya administrasi worker yang memakai nama `remote_*`. Operasi execution, shell, job, filesystem, patch, dan browser berbagi schema yang sama secara lokal dan remote. Menentukan machine juga memerlukan OAuth scope `remote:use`.

## Worker persisten

Hasil undangan berisi perintah spesifik platform:

- `persistent_command` memasang dan memulai user service di Linux atau macOS.
- `powershell_persistent_command` memasang dan memulai Windows user task dari PowerShell.

Di Windows, `local-shell-mcp worker install-service` mendaftarkan task `local-shell-mcp-worker` untuk pengguna saat ini. Task langsung dimulai, dimulai lagi ketika pengguna tersebut login setelah reboot, mengizinkan operasi dengan baterai, mengabaikan start duplikat, dan mencoba ulang run yang gagal. Tidak memerlukan hak administrator dan tidak berjalan sebelum pengguna masuk.

Gunakan lifecycle commands yang sama di setiap platform:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

Worker log disimpan di worker state directory sebagai `worker.log`.

## Kapabilitas

Worker mendukung shell/persistent shell sessions, tracked jobs, operasi filesystem, transfer internals, eksekusi Python, patches, dan Playwright jika dependensinya terpasang. Git menggunakan perintah standar melalui `run_shell(machine=...)`.

## Keamanan dan versi

Worker yang bergabung memberi MCP client kendali atas lingkungan yang dikonfigurasi. Gunakan invite TTL singkat, work directory atau akun khusus, tinjau audit log, dan cabut worker setelah tugas. Undangan yang dibuat memasang worker code yang sesuai dengan versi control server.

## Pemecahan masalah

Jika worker tidak muncul, periksa akses HTTPS keluar, keterjangkauan public base URL, kedaluwarsa undangan, waktu sistem, dan log control server.
