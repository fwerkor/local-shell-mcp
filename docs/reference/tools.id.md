<!-- i18n-source-sha256: af025099e696ea85872f77e88135d41d859705ccba72919cd4adb62f1e494dad -->
# Referensi tools

Page ini dibangun dari MCP tool schemas yang sebenarnya. Jalankan `python scripts/generate-tools-reference.py` setelah mengubah public tool surface untuk memperbarui English reference.

Sebagian besar tool mengembalikan `ToolResult` terstruktur berisi `ok`, `message`, dan `data`. `workspace_open` mengembalikan state yang terlihat model untuk merender MCP App. Kebanyakan tool eksekusi dan file menerima `machine` opsional; abaikan untuk workspace controller dan isi untuk worker terhubung. Operasi Git sengaja memakai `run_shell` atau tool shell lain, bukan wrapper Git khusus.

## Panduan pemilihan

| Kebutuhan | Tools yang disarankan |
|---|---|
| Memantau atau berkolaborasi dengan eksekusi di ChatGPT | `workspace_open` |
| Menginspeksi environment | `environment_get`, `file_tree`, `file_read` |
| Menjalankan command singkat atau Git operation | `run_shell` |
| Menjalankan task interaktif atau panjang | `shell_start` or `job_start` |
| Membuat perubahan file yang presisi | `file_edit` or `file_patch` |
| Mentransfer file atau directory | `remote_transfer` |
| Menemukan external MCP capability | `mcp_tool_search`, then `mcp_tool_inspect` |
| Berinteraksi dengan page | `browser_session`, `browser_snapshot`, then `browser_act` |
| Menjalankan custom browser logic | `browser_run_script` |
| Kontrol aplikasi desktop asli | `gui_list`, `gui_state`, then `gui_action` |
| Bekerja pada remote machine | gunakan tool yang sama dengan `machine`; gunakan `remote_*` hanya untuk worker administration |

## Interactive workspace

### `workspace_open`

Buka atau gunakan kembali Live Workspace yang menampilkan Logical Session yang diberikan secara eksplisit. Berikan session_id aktif yang dikembalikan session_manage. Workspace tidak pernah menyimpulkan identitas task dari transport MCP; berikan null secara eksplisit saat tidak ada Logical Session aktif.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

## Environment, Skills, dan task state

### `environment_get`

Mengembalikan version, workspace, auth, policy, dan environment information secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `skill_list`

Mencantumkan installed Agent Skills tanpa memuat instructions. MCP tool surface tetap tetap; penambahan atau penghapusan Skill directories terlihat pada call berikutnya.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

Memuat installed Skill dengan exact name yang dikembalikan `skill_list`. Mengembalikan instructions lengkap `SKILL.md` dan related file paths.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Membaca satu related text file dari installed Skill.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Memindai local workspace text files untuk common secrets sebelum commit atau push.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Kelola satu Logical Session durable. start membuat task baru dan mengembalikan session_id-nya. resume hanya melanjutkan session_id eksplisit yang diberikan pengguna atau yang sudah ada dalam percakapan ini. Semua action selain start memerlukan session_id. Action: start, resume, get, report, finish, cancel, delete. report menerima summary/findings/next/blockers/objective/label; delete memerlukan Session terminal.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `label` | `string \| null` | `null` |  |
| `objective` | `string \| null` | `null` |  |
| `summary` | `string \| null` | `null` |  |
| `findings` | `array[string] \| null` | `null` |  |
| `next` | `string \| null` | `null` |  |
| `blockers` | `array[string] \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `plan_manage`

Kelola Goal mode opsional untuk Logical Session eksplisit. Plan aktif mengaktifkan continuation otomatis setelah 15 menit tanpa aktivitas agent, maksimal 10 percobaan. session_id harus sama dengan id durable yang dikembalikan session_manage. Action: start, get, update, block, resume, finish, cancel. start memerlukan objective dan steps; finish mengharuskan semua steps completed atau skipped.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string` | required |  |
| `objective` | `string \| null` | `null` |  |
| `steps` | `array[object] \| null` | `null` |  |
| `step_id` | `string \| null` | `null` |  |
| `status` | `string \| null` | `null` |  |
| `text` | `string \| null` | `null` |  |
| `note` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `audit_tail`

Membaca recent local audit log entries.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells dan jobs

### `run_shell`

Menjalankan satu non-interactive shell command secara lokal atau pada remote machine. Gunakan untuk build, test, package-manager, Git, dan inspection commands yang harus selesai segera. Untuk process long-running, interactive, atau streaming gunakan `shell_start` atau `job_start`. Optional purpose/explanation fields dapat menjelaskan alasan command dijalankan.

Dengan `persist_on_timeout=true` (bawaan false), pekerjaan yang sama tetap berjalan setelah batas waktu dan mengembalikan `job_id`. Gunakan `job_tail`; stdout dan stderr digabung.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `persist_on_timeout` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `run_python`

Menulis dan menjalankan short Python script secara lokal atau pada remote machine.

Dengan `persist_on_timeout=true` (bawaan false), pekerjaan yang sama tetap berjalan setelah batas waktu dan mengembalikan `job_id`. Gunakan `job_tail`; stdout dan stderr digabung.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `persist_on_timeout` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `shell_start`

Memulai persistent interactive shell secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `idempotency_key` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `shell_send`

Mengirim input ke persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `idempotency_key` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `shell_read`

Membaca recent output dari persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `shell_stop`

Menghentikan persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `idempotency_key` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `shell_list`

Mencantumkan persistent shell sessions secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `job_start`

Memulai tracked long-running job secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `idempotency_key` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `job_list`

Mencantumkan tracked jobs secara lokal atau pada remote machine. Job aktif dikembalikan lebih dulu; `limit` dibatasi ke rentang 1-1000.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `job_tail`

Membaca recent output dari tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `job_stop`

Menghentikan tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `job_retry`

Memulai ulang stopped/exited tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `idempotency_key` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

## Files dan transfer

### `file_list`

Mencantumkan files dan directories secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `file_tree`

Mengembalikan compact directory tree secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `file_glob`

Mencari paths berdasarkan glob secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `file_grep`

Mencari isi files secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `file_read`

Membaca satu file atau list files secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `image_view`

Menampilkan PNG, JPEG, GIF, atau WebP sebagai native MCP image content secara lokal atau pada remote machine. Gunakan alih-alih `file_read` saat visual inspection diperlukan. Remote images menggunakan kembali file-transfer protocol yang ada, sehingga worker tidak memerlukan image-specific RPC.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `file_write`

Menulis UTF-8 text file secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `file_edit`

Menerapkan satu atau lebih exact-text edits pada local/remote file. Setiap edit berisi old, new, dan optional `replace_all`; old harus exact match termasuk whitespace dan indentation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `file_delete`

Menghapus local/remote file atau directory. `recursive=false` menghapus files atau empty directories; non-empty directories memerlukan `recursive=true` dan harus digunakan dengan hati-hati.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `file_patch`

Memeriksa dan menerapkan unified diff atau file_patch envelope secara lokal atau remote.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `remote_transfer`

Memulai job terlacak yang menyalin file atau directory antara controller dan remote machine. Remote upload memakai chunk raw-binary resumable; kelola transfer dengan `job_list`, `job_tail`, `job_stop`, dan `job_retry`.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Setidaknya satu dari `source_machine` dan `destination_machine` harus diberikan. Endpoint yang dihilangkan berarti workspace controller; source dapat berupa file atau directory.

### `link_create`

Membuat temporary browser-accessible URL untuk local file. Default response adalah attachment download; set `inline=true` untuk render langsung di browser atau Markdown image. Links adalah public bearer URLs yang dilindungi high-entropy token, TTL, optional download-count limit, dan explicit revocation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Mencantumkan generated local file download URLs.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Mencabut generated local file download URL.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamic MCP gateway

### `mcp_manage`

Mendaftarkan, mencantumkan, mengambil, mengaktifkan, menonaktifkan, refresh, menghapus, atau memperbarui isolated environment/headers dari dynamic MCP servers. Gunakan transport `stdio` dengan command/args/cwd atau `streamable_http` dengan url. Secret env/header values dipersist secara privat dan tidak pernah dikembalikan.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `transport` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `args` | `array[string] \| null` | `null` |  |
| `cwd` | `string \| null` | `null` |  |
| `url` | `string \| null` | `null` |  |
| `env` | `object \| null` | `null` |  |
| `headers` | `object \| null` | `null` |  |
| `enabled` | `boolean` | `true` |  |
| `overwrite` | `boolean` | `false` |  |
| `refresh` | `boolean` | `true` |  |
| `key` | `string \| null` | `null` |  |
| `value` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Mencari cached lightweight tool summaries dari enabled dynamic MCP servers. Dynamic tools tetap di luar `tools/list` server ini; gunakan returned `<server>:<tool>` name dengan `mcp_tool_inspect` sebelum call.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

Mengembalikan full cached schema dari dynamic MCP tool bernama `<server>:<tool>`. Refresh server dengan `mcp_manage` jika cache stale.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Memanggil cached dynamic MCP tool bernama `<server>:<tool>`. Discover dengan `mcp_tool_search` dan inspect schema dengan `mcp_tool_inspect` terlebih dahulu. External MCP connections hanya dibuka selama call ini.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Memulai, mencantumkan, menutup, atau membersihkan persistent high-level browser sessions secara lokal atau remote. `start` dapat membuka URL, reuse persistent `profile_id`, atau load `storage_state_path`; `close` dapat save storage state.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `browser` | `string` | `"chromium"` |  |
| `headless` | `boolean` | `true` |  |
| `width` | `integer` | `1440` |  |
| `height` | `integer` | `1000` |  |
| `url` | `string \| null` | `null` |  |
| `wait_until` | `string` | `"domcontentloaded"` |  |
| `profile_id` | `string \| null` | `null` |  |
| `storage_state_path` | `string \| null` | `null` |  |
| `save_storage_state_path` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `browser_snapshot`

Capture persistent browser page: title, URL, bounded visible text, interactive elements dengan stable short refs seperti `e1`, recent page/network errors, dan optional screenshot path. Gunakan refs langsung sebagai `browser_act` targets sampai page navigate atau snapshot baru diambil.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `browser_act`

Menjalankan structured actions dalam persistent browser session. Mendukung navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text, dan wait_for_url. `target` dapat berupa `browser_snapshot` ref seperti `e1` atau CSS selector. Gunakan `browser_run_script` hanya jika high-level actions tidak cukup.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

### `browser_run_script`

Menjalankan full Python Playwright script secara lokal atau pada remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.

## Otomatisasi GUI desktop

### `gui_list`

Daftar jendela aplikasi desktop yang terlihat dan kemampuan backend GUI secara lokal atau jarak jauh.

| Parameter | Jenis | Wajib/default | Keterangan |
|---|---|---|---|
| `machine` | `tali \| batal` | `null` |  |
| `logical_session_id` | `tali \| batal` | diperlukan | Sesi Logis untuk panggilan alat ini. Lewati session_id yang dikembalikan oleh session_manage saat mengerjakan tugas itu. Gunakan null hanya jika tidak ada Sesi Logis yang aktif. Ini adalah session_id tahan lama yang sama yang digunakan oleh session_manage. |

Cakupan OAuth: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Ketika `machine` diberikan, panggilan tersebut juga memerlukan `remote:use` dan dijalankan melalui protokol pekerja jarak jauh.

### `gui_state`

Amati satu jendela desktop sebelum bertindak. Mengembalikan elemen aksesibilitasnya ditambah tangkapan layar MCP asli opsional dan state_id yang berumur pendek. Lebih suka tindakan element_id; tindakan koordinat bersifat relatif terhadap jendela yang diamati dan ditolak jika jendela dipindahkan atau diubah ukurannya.

| Parameter | Jenis | Wajib/default | Keterangan |
|---|---|---|---|
| `window_id` | `string` | diperlukan |  |
| `screenshot` | `boolean` | `true` |  |
| `include_elements` | `boolean` | `true` |  |
| `max_elements` | `integer` | `300` |  |
| `max_depth` | `integer` | `12` |  |
| `machine` | `tali \| batal` | `null` |  |
| `logical_session_id` | `tali \| batal` | diperlukan | Sesi Logis untuk panggilan alat ini. Lewati session_id yang dikembalikan oleh session_manage saat mengerjakan tugas itu. Gunakan null hanya jika tidak ada Sesi Logis yang aktif. Ini adalah session_id tahan lama yang sama yang digunakan oleh session_manage. |

Cakupan OAuth: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Ketika `machine` diberikan, panggilan tersebut juga memerlukan `remote:use` dan dijalankan melalui protokol pekerja jarak jauh.

### `gui_action`

Jalankan tindakan GUI terhadap observasi gui_state baru secara lokal atau jarak jauh. state_id hanya sekali pakai. Lebih memilih penargetan elemen_id semantik; koordinat x/y mentah bersifat relatif terhadap jendela. Tindakan yang didukung adalah klik, klik ganda, klik kanan, pindahkan, gulir, seret, ketik, kunci, set_nilai, fokus, dan tunggu.

| Parameter | Jenis | Wajib/default | Keterangan |
|---|---|---|---|
| `window_id` | `string` | diperlukan |  |
| `state_id` | `string` | diperlukan |  |
| `actions` | `array[GuiAction]` | diperlukan |  |
| `machine` | `tali \| batal` | `null` |  |
| `logical_session_id` | `tali \| batal` | diperlukan | Sesi Logis untuk panggilan alat ini. Lewati session_id yang dikembalikan oleh session_manage saat mengerjakan tugas itu. Gunakan null hanya jika tidak ada Sesi Logis yang aktif. Ini adalah session_id tahan lama yang sama yang digunakan oleh session_manage. |

Cakupan OAuth: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Ketika `machine` diberikan, panggilan tersebut juga memerlukan `remote:use` dan dijalankan melalui protokol pekerja jarak jauh.

## Remote worker administration

### `remote_manage`

Mengelola remote workers dengan action=invite, list, revoke, atau rename. invite menerima name/workdir/ttl_s; revoke memerlukan machine; rename memerlukan machine dan new_name.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session untuk pemanggilan tool ini. Saat mengerjakan task, berikan session_id yang dikembalikan session_manage. Gunakan null hanya ketika tidak ada Logical Session aktif. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Saat `machine` diberikan, call juga memerlukan `remote:use` dan dijalankan melalui protokol remote worker.
