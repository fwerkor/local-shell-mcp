<!-- i18n-source-sha256: 276e9356b895a85759d31467512bdc530c9baa216a368df4ef1bccce39530d0e -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">Własny obszar roboczy AI · Płaszczyzna kontroli MCP</span>

# local-shell-mcp

Czatuj, projekty, pliki, terminale, zdalne maszyny i narzędzia AI w jednym hostowanym interfejsie. Podłącz zewnętrznych klientów MCP, kiedy ich potrzebujesz.

<div class="hero-actions" markdown>
[Zacznij](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Referencja tools](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Prawdziwe środowisko coding
Uruchamiaj tests, sprawdzaj repositories, patch files, obsługuj Git i zachowuj audit trail z jednego MCP endpoint.
</div>

<div class="feature-card" markdown>
### Ujednolicony internetowy obszar roboczy
Korzystaj z wbudowanej historii czatu i projektu wraz z plikami kontrolera, terminalami, pulpitem, sesjami, pilotami i audytem. Zewnętrzni klienci MCP pozostają opcjonalni.
</div>

<div class="feature-card" markdown>
### Kontrola remote machines
Podłączaj machines za NAT, firewall lub HPC przez outbound worker connections bez otwierania portów SSH.
</div>
</div>

## Co zapewnia

`local-shell-mcp` zapewnia ujednoliconą, hostowaną przestrzeń roboczą AI i serwer MCP dla klientów zewnętrznych. Zapewnia powłokę, trwałą powłokę, system plików, wyszukiwanie, łatkę, Git, Playwright, audyt, trwałe sesje logiczne z opcjonalnymi planami celów, tokenizowane łącze do plików i narzędzia do pracy zdalnej za pośrednictwem uwierzytelnionych punktów końcowych MCP.

Używaj, gdy AI musi inspect repository, uruchamiać tests, edit files, operate Git, zbierać browser evidence, tworzyć downloadable artifacts lub kontrolować remote machine, która może tylko outbound connect do control server.

## Architektura

```text
Warstwa runtime: Docker / VS Code extension / binary / Python / stdio
Warstwa exposure: localhost / HTTPS proxy / tunnel / stdio pipe
Warstwa klienta: ujednolicony WebUI / Gemini / ChatGPT / ogólny klient MCP
Kontrolowany workspace: /workspace or configured workspace root
Optional remote workers: outbound machine connections
```

Docelową isolation boundary jest container lub VM uruchamiający service.

## Zacznij według scenariusza

| Scenariusz | Zacznij tutaj | Dlaczego |
|---|---|---|
| Podstawowy obszar roboczy przeglądarki | [Unified web workspace](getting-started/web-workspace.md) | Czat, projekty i strony kontrolne LSM ze wspólnym loginem |
| Pierwsze wdrożenie kontrolera | [Quickstart](getting-started/quickstart.md) | Zalecana instalacja ze źródeł, OAuth i pierwsza sesja przeglądarki. |
| Wybór runtime layer | [Runtime choices](guides/deployment.md) | Opisuje Docker, VS Code, binary, Python i stdio jako osobne runtime options |
| Łączenie Gemini Spark | [Gemini Custom Apps](getting-started/gemini-spark.md) | Kwalifikowalność, adres URL HTTPS MCP, OAuth i testowanie |
| Dodanie ChatGPT jako client | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, pierwszy bezpieczny prompt, tool discovery |
| Dodać LSM do DeepSeek Harness | [Plugin DeepSeek Harness](clients/deepseek-harness.md) | Zainstalować repository jako DSH bundle, zachowując pełną powierzchnię narzędzi LSM i remote workers |
| Uruchomienie z VS Code | [VS Code extension runtime](installation/vscode-extension.md) | Editor-launched runtime i uwagi host safety |
| Nauka obsługi toolset | [Usage patterns](guides/usage-patterns.md) | Prompt templates i tool-choice guidance |
| Zrozumienie każdego tool | [Tools reference](reference/tools.md) | Purpose, inputs, returns, combinations i notes dla każdego tool |
| Podłączenie HPC, NPU/GPU lub server node | [Remote workers](guides/remote-workers.md) | Outbound worker join flow i remote tool usage |
| Udostępnianie generated files | [File links](guides/file-links.md) | Tokenized download URLs z TTL i revoke |
| Hardening deployment | [Security](security.md) | Isolation, OAuth, workspace scope i audit logs |

## Główne tool families

| Family | Przykłady | Zastosowanie |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, tests, scripts, long-running processes |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository inspection i precise edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Reviewable source-control workflows |
| Sessions i goals | `session_manage`, `plan_manage` | Trwały task handoff, progress report i opcjonalny Goal mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistent interaction, UI checks, screenshots, rendered docs i page text |
| File links | `link_create`, `link_revoke` | Download generated artifacts z chat |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | Machines za NAT, firewalls lub cluster login flows |

## Typowe workflows

### Kodowanie w internetowym obszarze roboczym

1. Uruchom kontroler LSM i opcjonalny plik [unified web workspace](getting-started/web-workspace.md).
2. Otwórz `/ui` i zaloguj się przy użyciu tożsamości LSM.
3. Skonfiguruj punkt końcowy modelu i otwórz nową konwersację.
4. Poproś model o sprawdzenie repozytorium i najpierw przeprowadzenie kontroli w trybie tylko do odczytu.
5. Po zatwierdzeniu pozwól na patch files, tests, diff review, commit i push.
6. Sprawdź audit log, gdy task dotyczy file links lub remote systems.

### Remote HPC lub accelerator host

1. Utwórz one-time remote worker invite.
2. Wklej generated command na remote host.
3. Używaj normal tools z `machine`; Git przez `run_shell`, transfer przez `remote_transfer`.
4. Po task revoke worker.

### Artifact generation

1. Pozwól AI generate file pod `/workspace`.
2. Utwórz tokenized file link z TTL/download limits.
3. Udostępnij link w chat.
4. Po zakończeniu revoke.

## Język

Ta site jest buildowana natywnym MkDocs i18n plugin. Użyj language selector w header, aby przełączać English i translated pages. Pages bez translation fallbackują do English.
