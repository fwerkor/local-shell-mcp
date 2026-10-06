<!-- i18n-source-sha256: 382c9edbbba8fa4fb3aab11dcc4127ba80bff8c7104bdedffdf66b9bbcdb744a -->
# Kullanım kalıpları ve prompting kılavuzu

`local-shell-mcp` güçlü tools sunar. İyi sonuçlar için modelden önce inceleme, küçük adımlarla hareket etme, doğrulama ve nelerin değiştiğini raporlama istenmelidir.

## Genel çalışma döngüsü

Çoğu coding task için bu döngüyü kullanın:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read` ve `git status` gibi komutlar için `run_shell`.
2. Plan: modelden ilgili minimum files ve tests kümesini belirlemesini isteyin.
3. Edit: `file_edit`, `file_patch` veya shell commands kullanın.
4. Verify: `run_shell` veya persistent shells ile targeted tests/builds çalıştırın.
5. Review: `run_shell` üzerinden `git diff`, gerektiğinde `secret_scan` ve `audit_tail` çalıştırın.
6. Commit/export: `run_shell` üzerinden explicit Git CLI commands veya `link_create` kullanın.

## Tool seçimi

| Task | Tercih et | Kaçın |
|---|---|---|
| Kısa one-shot command | `run_shell` | Her command için persistent shell başlatmak |
| Uzun dev server, REPL, watch task | `shell_start` + `shell_read` + `shell_send` | `run_shell`u timeout’a kadar bloklamak |
| Structured analysis veya file generation | `run_python` | Karmaşık JSON/text için kırılgan shell pipelines |
| Küçük exact edit | `file_edit` | Gereksiz tüm dosya rewrite |
| Bir dosyada bir veya birkaç replacement | `file_edit` with an `edits` array | Yeniden okumadan stale edit tekrarlamak |
| Multi-file patch | `file_patch` | Ad hoc shell edit |
| File bulma | `file_tree`, `file_glob` | Büyük repository’lerin tam recursive listing’i |
| Code bulma | `file_grep` | Çok sayıda file’ı körlemesine okumak |
| Browser evidence | `browser_snapshot`, `browser_run_script` | Page name veya route’dan tahmin etmek |
| Downloadable artifacts | `link_create` | Büyük binary content’i chat’e yapıştırmak |
| Remote machine work | normal tools with `machine`, plus `remote_transfer` | Outbound worker yeterliyken inbound SSH açmak |

## CLI üzerinden araç çağırma

Shell betikleri ve CI için `lsm call <tool>`, çalışan loopback controller üzerinden aynı kayıtlı araç yüzeyini çağırır; böylece remote worker ve controller durumu korunur.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Çağrıyı bir Logical Session ile ilişkilendirmek için `--session s_...` kullanın. Belgelenen Docker Compose kurulumunda ham `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN` yalnızca host tarafından sahip olunan ve izinleri kısıtlanmış `.env` içinde kalır; Compose controller’a yalnızca SHA-256 doğrulayıcısını aktarır. Diğer ayrık runtime düzenleri `--token-file <path>` kullanabilir. `--direct` controller katmanını atlar, geçerli `.env` runtime ayarlarını süreç içinde uygular, host CLI token değerini araç ortamına enjekte etmez ve yalnızca yerel çağrılar içindir. Human UI token `/mcp` tarafından hiçbir zaman kabul edilmez; ayrık runtime controller’ı eşleşen `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256` değerini yapılandırmalıdır.

## Prompt şablonları

### Read-only repository orientation

```text
local-shell-mcp kullan. repository layout ve git status’u incele. Dosyaları değiştirme. Değişiklikten önce ana component’leri, çıkarabildiğin test command’larını ve belirgin riskleri özetle.
```

### Focused bug fix

```text
Bug’ı düzeltmek için local-shell-mcp kullan. Önce en küçük relevant command ile reproduce veya locate et. Edit öncesi dosyaları oku. Minimal patch yap, targeted verification çalıştır, sonra git diff ve çalıştırılan tam tests listesini göster. Ben onaylamadan commit yapma.
```

### Commit ve push workflow

```text
local-shell-mcp kullan. git status ve diff’i kontrol et, relevant tests ve secret_scan çalıştır, kısa mesajlı tek focused commit oluştur, sonra current branch’i push et. Cache, build artifacts veya unrelated formatting ekleme.
```

### Long-running process

```text
Dev server’ı persistent shell session içinde başlat, ready olana kadar output’u oku, sonra browser tools ile page’i doğrula. session id’yi tut ve doğrulamadan sonra session’ı kill et.
```

### Remote worker task

```text
Bağlı remote worker <machine> kullan. Önce machine=<machine> ile environment_get, sonra aynı machine ile file_list çağır. Yalnız configured remote workdir içinde çalış. Kısa command için run_shell, uzun iş için shell_start veya job_start kullan.
```

## Repositories ile çalışma

Open-source değişiklikler için önerilen sequence:

1. `run_shell` ile `git status --short --branch` çalıştır.
2. Upstream state önemliyse explicit Git CLI ile fetch ve branch inspect yap.
3. Edit öncesi `file_grep` ve `file_read` kullan.
4. Minimal patch yap.
5. Önce targeted tests, sonra uygunsa broader tests çalıştır.
6. Commit/push öncesi `secret_scan` çalıştır.
7. Explicit stage ve kısa mesajlı commit yap.

Maintainer’ların review edebileceği history için logical change başına bir commit isteyin.

## Generated artifacts ile çalışma

PDF, report, screenshot, archive veya log için:

1. File’ı workspace içinde generate et.
2. File’ın varlığını ve expected size’ı doğrula.
3. Kısa TTL ve optional `max_downloads` ile `link_create` kullan.
4. Artık gerekmiyorsa link’i revoke et.

Private key, credential directory veya unrelated personal data için public link oluşturmayın.

## Remote machines ile çalışma

Remote worker mode, machine outbound HTTPS yapabildiği ancak inbound SSH kabul edemediği durumlarda yararlıdır.

İyi uygulamalar:

- `remote_manage(action="invite", ...)` veya `remote_manage(action="rename", ...)` ile machine oluştur/rename et.
- İşlemden önce `environment_get(machine=...)` çağır.
- `remote_transfer` ile controller/worker veya worker/worker transfer jobs başlat ve normal `job_*` tools ile yönet.
- Task sonrasında `remote_manage(action="revoke", ...)` ile worker revoke et.

## Anti-patterns

Environment disposable değilse ve sonuçlar tam anlaşılmıyorsa şu talimatlardan kaçının:

- Host-launched server’da “gereken her şeyi global install et”.
- Time bound veya verification criteria olmadan “çalışana kadar çalıştır”.
- Generated artifacts içeren repository’de “her şeyi commit et”.
- Kolaylık için “tüm home directory’yi expose et”.
- “Tüm workspace için file link oluştur”.
- `LOCAL_SHELL_MCP_AUTH_MODE=none` ile public deployment çalıştırmak.
