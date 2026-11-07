<!-- i18n-source-sha256: 276e9356b895a85759d31467512bdc530c9baa216a368df4ef1bccce39530d0e -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">Kendi kendine barındırılan yapay zeka çalışma alanı · MCP kontrol düzlemi</span>

# local-shell-mcp

Kendi kendine barındırılan tek bir arayüzde sohbet, projeler, dosyalar, terminaller, uzak makineler ve yapay zeka araçları. İhtiyacınız olduğunda harici MCP istemcilerini bağlayın.

<div class="hero-actions" markdown>
[Başla](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Tools referansı](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Gerçek coding environment
Tek MCP endpoint üzerinden tests çalıştırın, repositories inceleyin, files patch edin, Git kullanın ve audit trail tutun.
</div>

<div class="feature-card" markdown>
### Birleşik web çalışma alanı
Denetleyici dosyaları, terminaller, masaüstü, oturumlar, uzaktan kumandalar ve denetimin yanı sıra yerleşik sohbet ve proje geçmişini kullanın. Harici MCP istemcileri isteğe bağlı kalır.
</div>

<div class="feature-card" markdown>
### Remote machine control
SSH ports açmadan outbound worker connections ile NAT, firewall veya HPC machines bağlayın.
</div>
</div>

## Neler sağlar

`local-shell-mcp`, harici istemciler için birleşik, kendi kendine barındırılan bir yapay zeka çalışma alanı ve bir MCP sunucusu sağlar. Kimliği doğrulanmış MCP uç noktaları aracılığıyla kabuk, kalıcı kabuk, dosya sistemi, arama, yama, Git, Oyun Yazarı, denetim, isteğe bağlı Hedef planları ile dayanıklı mantıksal oturumlar, tokenleştirilmiş dosya bağlantısı ve uzaktan çalışma araçları sağlar.

AI’ın repository incelemesi, tests çalıştırması, files düzenlemesi, Git kullanması, browser evidence toplaması, downloadable artifacts üretmesi veya yalnız control server’a outbound bağlanabilen remote machine’i kontrol etmesi gerektiğinde kullanın.

## Mimari

```text
Runtime katmanı: Docker / VS Code extension / binary / Python / stdio
Exposure katmanı: localhost / HTTPS proxy / tunnel / stdio pipe
İstemci katmanı: birleştirilmiş WebUI / Gemini / ChatGPT / genel MCP istemcisi
Kontrollü workspace: /workspace or configured workspace root
Optional remote workers: outbound machine connections
```

Amaçlanan isolation boundary, service’in çalıştığı container veya VM’dir.

## Senaryoya göre başla

| Senaryo | Buradan başla | Neden |
|---|---|---|
| Birincil tarayıcı çalışma alanı | [Unified web workspace](getting-started/web-workspace.md) | Paylaşılan oturum açmayla sohbet, projeler ve LSM kontrol sayfaları |
| İlk Denetleyici dağıtımı | [Quickstart](getting-started/quickstart.md) | Önerilen kaynak dağıtımı, OAuth ve ilk tarayıcı oturumu. |
| runtime layer seçimi | [Runtime choices](guides/deployment.md) | Docker, VS Code, binary, Python ve stdio’yu ayrı runtime options olarak açıklar |
| Gemini Spark'ı Bağlama | [Gemini Custom Apps](getting-started/gemini-spark.md) | Uygunluk, HTTPS MCP URL'si, OAuth ve test |
| ChatGPT’yi client olarak ekleme | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, ilk güvenli prompt, tool discovery |
| LSM’yi DeepSeek Harness’a eklemek | [DeepSeek Harness plugin](clients/deepseek-harness.md) | Bu repository’yi DSH bundle olarak kurarken tam LSM tool ve remote-worker surface’i koru |
| VS Code’dan çalıştırma | [VS Code extension runtime](installation/vscode-extension.md) | Editor-launched runtime ve host safety notları |
| toolset kullanmayı öğrenme | [Usage patterns](guides/usage-patterns.md) | Prompt templates ve tool-choice guidance |
| Her tool’u anlama | [Tools reference](reference/tools.md) | Her tool için purpose, inputs, returns, combinations ve notes |
| HPC, NPU/GPU veya server node bağlama | [Remote workers](guides/remote-workers.md) | Outbound worker join flow ve remote tool usage |
| Generated files paylaşma | [File links](guides/file-links.md) | TTL ve revoke destekli tokenized download URLs |
| Deployment hardening | [Security](security.md) | Isolation, OAuth, workspace scope ve audit logs |

## Ana tool family’leri

| Family | Örnekler | Kullanım |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, tests, scripts, long-running processes |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository inspection ve precise edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Reviewable source-control workflows |
| Sessions ve goals | `session_manage`, `plan_manage` | Kalıcı task handoff, progress report ve optional Goal mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistent interaction, UI checks, screenshots, rendered docs, page text |
| File links | `link_create`, `link_revoke` | Chat’ten generated artifacts indirme |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | NAT, firewalls veya cluster login flows arkasındaki machines |

## Tipik workflows

### Web çalışma alanında kodlama

1. Bir LSM Denetleyicisini ve isteğe bağlı [unified web workspace](getting-started/web-workspace.md)'yi başlatın.
2. `/ui`'i açın ve LSM kimliğini kullanarak oturum açın.
3. Bir model uç noktası yapılandırın ve yeni bir konuşma açın.
4. Modelden depoyu incelemesini ve önce salt okunur kontrolleri çalıştırmasını isteyin.
5. Onay sonrası patch files, tests, diff review, commit ve push işlemlerine izin verin.
6. File links veya remote systems içeren task’larda audit log’u inceleyin.

### Remote HPC veya accelerator host

1. One-time remote worker invite oluşturun.
2. Generated command’i remote host’a yapıştırın.
3. Normal tools ile `machine` kullanın; Git için `run_shell`, transfer için `remote_transfer`.
4. Task sonrasında worker’ı revoke edin.

### Artifact generation

1. AI’ın `/workspace` altında file generate etmesini sağlayın.
2. TTL/download limits içeren tokenized file link oluşturun.
3. Link’i chat’te paylaşın.
4. Bitince revoke edin.

## Dil

Bu site native MkDocs i18n plugin ile build edilir. Header’daki language selector ile English ve translated pages arasında geçiş yapın. Translation olmayan pages English’e fallback eder.
