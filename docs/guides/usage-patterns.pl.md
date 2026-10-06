<!-- i18n-source-sha256: bfd205813bd40569d489f7e57417eef5098af2388cdb852b1016deb74a2fc0f1 -->
# Wzorce użycia i przewodnik prompting

`local-shell-mcp` udostępnia potężne tools. Dobre wyniki wymagają, by model najpierw sprawdził środowisko, działał małymi krokami, wykonał weryfikację i opisał zmiany.

## Ogólna pętla działania

Używaj tej pętli dla większości coding tasks:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read` oraz `run_shell` dla poleceń takich jak `git status`.
2. Plan: poproś model o wskazanie minimalnego zestawu files i tests.
3. Edit: użyj `file_edit`, `file_patch` lub shell commands.
4. Verify: uruchom targeted tests/builds przez `run_shell` lub persistent shells.
5. Review: uruchom `git diff` przez `run_shell`, a gdy potrzebne `secret_scan` i `audit_tail`.
6. Commit/export: użyj explicit Git CLI commands przez `run_shell` lub `link_create`.

## Wybór tool

| Task | Preferuj | Unikaj |
|---|---|---|
| Krótki one-shot command | `run_shell` | Uruchamiania persistent shell dla każdego command |
| Długi dev server, REPL, watch task | `shell_start` + `shell_read` + `shell_send` | Blokowania `run_shell` do timeout |
| Structured analysis lub file generation | `run_python` | Kruchych shell pipelines dla złożonego JSON/text |
| Mały exact edit | `file_edit` | Niepotrzebnego przepisywania całych plików |
| Jedna lub kilka zamian w pliku | `file_edit` with an `edits` array | Powtarzania stale edits bez ponownego odczytu |
| Multi-file patch | `file_patch` | Ad hoc shell edits |
| Wyszukiwanie files | `file_tree`, `file_glob` | Pełnych recursive listings dużych repositories |
| Wyszukiwanie code | `file_grep` | Czytania wielu plików w ciemno |
| Browser evidence | `browser_snapshot`, `browser_run_script` | Zgadywania po nazwach page/route |
| Downloadable artifacts | `link_create` | Wklejania dużego binary content do chat |
| Remote machine work | normal tools with `machine`, plus `remote_transfer` | Otwierania inbound SSH, gdy outbound worker wystarcza |

## Wywoływanie narzędzi z CLI

W skryptach shell i CI polecenie `lsm call <tool>` wywołuje ten sam zarejestrowany zestaw narzędzi przez działający loopback controller, dzięki czemu zachowany jest stan remote workerów i controllera.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Użyj `--session s_...`, aby powiązać wywołanie z Logical Session. W udokumentowanej konfiguracji Docker Compose controller i CLI hosta współdzielą `LOCAL_SHELL_MCP_UI_LOCAL_TOKEN` przez ograniczony uprawnieniami plik `.env` w repository; inne rozdzielone układy runtime mogą użyć `--token-file <path>`. `--direct` pomija controller i działa wyłącznie lokalnie.

## Szablony prompt

### Read-only repository orientation

```text
Użyj local-shell-mcp. Sprawdź layout repository i git status. Nie modyfikuj plików. Przed zmianami podsumuj główne componenty, możliwe do wywnioskowania test commands i oczywiste risks.
```

### Focused bug fix

```text
Użyj local-shell-mcp do naprawy bug. Najpierw odtwórz lub zlokalizuj go najmniejszym relevant command. Przeczytaj pliki przed edit. Zrób minimal patch, uruchom targeted verification, potem pokaż git diff i dokładne tests. Nie rób commit przed moją zgodą.
```

### Workflow commit i push

```text
Użyj local-shell-mcp. Sprawdź git status i diff, uruchom relevant tests i secret_scan, utwórz jeden focused commit z krótkim message, potem push current branch. Nie dodawaj caches, build artifacts ani unrelated formatting.
```

### Long-running process

```text
Uruchom dev server w persistent shell session, czytaj output aż będzie ready, potem użyj browser tools do weryfikacji page. Zachowaj session id i kill session po weryfikacji.
```

### Remote worker task

```text
Użyj podłączonego remote worker o nazwie <machine>. Najpierw wywołaj environment_get z machine=<machine>, potem file_list z tą samą machine. Pracuj wyłącznie w configured remote workdir. Używaj run_shell dla krótkich commands i shell_start lub job_start dla długich zadań.
```

## Praca z repositories

Zalecana sequence dla zmian open-source:

1. Uruchom `git status --short --branch` przez `run_shell`.
2. Fetch i inspect branches explicit Git CLI, gdy upstream state ma znaczenie.
3. Używaj `file_grep` i `file_read` przed edit.
4. Zrób minimal patch.
5. Najpierw targeted tests, później broader tests, gdy to praktyczne.
6. Uruchom `secret_scan` przed commit lub push.
7. Jawnie stage i commit z krótkim message.

Proś o jeden commit na logical change, gdy maintainerzy potrzebują łatwej do review historii.

## Praca z generated artifacts

Dla PDF, report, screenshot, archive lub log:

1. Wygeneruj file w workspace.
2. Sprawdź, że file istnieje i ma expected size.
3. Użyj `link_create` z krótkim TTL i optional `max_downloads`.
4. Revoke link, gdy nie jest potrzebny.

Nie twórz public links dla private keys, credential directories ani unrelated personal data.

## Praca z remote machines

Remote worker mode jest przydatny, gdy machine może wykonywać outbound HTTPS, ale nie może przyjmować inbound SSH.

Dobre praktyki:

- Twórz lub rename machine przez `remote_manage(action="invite", ...)` albo `remote_manage(action="rename", ...)`.
- Przed działaniem wywołaj `environment_get(machine=...)`.
- Użyj `remote_transfer`, aby uruchamiać controller/worker lub worker/worker transfer jobs, a potem zarządzaj normalnymi `job_*` tools.
- Po task revoke worker przez `remote_manage(action="revoke", ...)`.

## Anti-patterns

Unikaj tych instrukcji, chyba że environment jest disposable i konsekwencje są zrozumiałe:

- „Zainstaluj globalnie wszystko, co potrzebne” na host-launched server.
- „Uruchamiaj aż zadziała” bez time bounds lub verification criteria.
- „Commit wszystko” w repository z generated artifacts.
- „Expose cały home directory” dla wygody.
- „Utwórz file link dla całego workspace”.
- Uruchamianie public deployment z `LOCAL_SHELL_MCP_AUTH_MODE=none`.
