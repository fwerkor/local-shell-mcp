<!-- i18n-source-sha256: cef0a90f9de3e2806e2a6bd8925217ea44ea6d6e6bce911eea09b1d4192a82d9 -->
# Runtime seçenekleri ve deployment modeli

`local-shell-mcp`'in iki tamamlayıcı kararı vardır:

1. **Runtime**: server process’in nasıl çalıştığı ve hangi workspace’i kontrol ettiği.
2. **Arayüz**: İsteğe bağlı [unified web workspace](../getting-started/web-workspace.md)'yi kullanın veya Gemini ya da ChatGPT gibi harici bir MCP istemcisine bağlanın.

**Controller için tek çalıştırılabilir dosya önerilir**, Python, Docker veya kaynak kod gerekmez. Diğer yöntemler de desteklenir.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Yalnızca yerel HTTP oluşturun Birleşik web çalışma alanı
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Yaygın olarak kendi kendine barındırılan bir kurulum:

```text
Tarayıcı -> https://chat.example.com (birleşik web çalışma alanı)
        -> kimliği doğrulanmış yerel kabuk-mcp Denetleyicisi
        -> kontrollü çalışma alanı ve giden İşçiler
İsteğe bağlı harici istemci -> https://mcp.example.com/mcp
```

Local MCP client setup daha basit olabilir:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

**Önerilir:** Genel erişim için herkese açık bir sunucuya dağıtın veya trafiği HTTPS ters vekiliyle herkese açık bir sunucu üzerinden iletin. **Önerilmez:** Cloudflare Tunnel üzerinden istemci tarafındaki yükleme hızı çok düşük olabilir; bu da dosya yükleme ve aktarımı işlevlerini kullanmayı zorlaştırır. Yalnızca genel sunucu veya yönlendirme mümkün değilse kullanın. ([Public HTTPS exposure](../clients/connectivity.md))

## Runtime seçim matrisi

| Çalışma zamanı | Şunun için en iyisi: | İzolasyon sınırı | Araç zinciri kaynağı | Harici MCP erişimi | Sayfa |
|---|---|---|---|---|---|
| **Tek dosya (önerilen)** | Desteklenen çoğu platform | Host or VM | Host tools ve configured executable | HTTPS proxy veya tunnel ekle | [Standalone binary](../installation/binary.md) |
| Docker Oluşturma | Yalıtılmış geçici konteynerler | Konteyner | Yalın Kontrolör görüntüsü; göreve özgü araç zincirlerini ayrı olarak kurun | HTTPS proxy'si veya tüneli ekleyin | [Docker Compose](../installation/docker.md) |
| Docker Compose + tünel sepeti | Önerilmez: Genel sunucu üzerinden yönlendirin; Cloudflare Tunnel son çare olsun | Konteyner | Proje resmi | Genel sunucu üzerinden yönlendirin; Cloudflare Tunnel son çare olsun | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Editor workspace içinden server start/stop | Genellikle host process | Host tools ve configured executable | ChatGPT için harici HTTPS tunnel/proxy ekle | [VS Code extension](../installation/vscode-extension.md) |
| Kaynak / pipx | Geliştirme ve özelleştirme | Host virtualenv or VM | Python package ve host tools | HTTPS proxy veya tunnel ekle | [Python install](../installation/python.md) |
| Stdio mode | Process’i doğrudan spawn eden local MCP client’lar | Client process boundary | Host tools ve configured executable | ChatGPT web/app ile kullanılamaz | [Stdio mode](../installation/stdio.md) |

## Client bağlantı matrisi

| Arayüz | Genel HTTPS gerektirir | `/mcp`'i kullanır | OAuth gerektirir | Tipik çalışma zamanı |
|---|---:|---:|---:|---|
| Birleşik LSM web çalışma alanı | Uzaktan erişim için evet; yerel proxy de mümkün | Dahili olarak | LSM'ye giriş | Denetleyici artı ayrı web yığını |
| Gemini Spark / Özel Uygulamalar | Evet | Evet | Evet genel kullanım için | Herhangi bir HTTP Denetleyicisi |
| ChatGPT custom MCP connector | Evet | Evet | Public kullanımda evet | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | Hayır | Hayır | Hayır | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | localhost için genelde hayır; ağlar arası evet | Evet | localhost dışında önerilir | Any HTTP runtime |
| VS Code extension helper flow | Yalnız ChatGPT bağlanacaksa | ChatGPT URL copy edilirken evet | ChatGPT için önerilir | VS Code-launched runtime |

[unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) ve [network connectivity](../clients/connectivity.md)'e bakın.

## Her runtime neyi kontrol eder

Her runtime aynı server code’u başlatır ve etkinleştirildiğinde aynı MCP tool family’lerini sunar:

- Shell ve persistent shell sessions.
- Filesystem, search ve patch tools.
- Git operations.
- Playwright ile browser automation.
- Audit log ve task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle ve machine-routed tools.

Fark abstract API değil, arkasındaki **operating environment**’dır.

| Soru | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Command nerede çalışır? | Container içinde | Genellikle host workspace üzerinde | Host veya VM process environment içinde |
| Default workspace? | Mounted `/workspace` | Geçerli VS Code folder veya configured path | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Derleyiciler ve tarayıcılar önceden kurulu mu? | HAYIR; görevin gerektirdiğini yükle | Yalnızca ana bilgisayara yüklenmişse | Yalnızca ana bilgisayara yüklenmişse |
| Reset kolay mı? | Container ve workspace volume yeniden oluştur | Workspace’e bağlı | Host/VM’e bağlı |
| Arbitrary package install için uygun mu? | Disposable ise evet | Host üzerinde daha riskli | VM dışında daha riskli |

## Önerilen seçim

**Tek dosyalık sürümü tercih edin**: platformunuza uygun dosyayı indirip sınırlı hesap ve ayrı workspace ile çalıştırın. [İkili kılavuzu](../installation/binary.md).

İş akışı bir düzenleyiciden başlatıldığında ve yerel bir başlatıcı istediğinizde **VS Code uzantısını** kullanın. Bu hala bir çalışma zamanıdır. Uzak web istemcilerinin ulaşılabilir bir HTTPS proxy'sine veya tüneline ihtiyacı vardır.

**Kaynak kurulumu** Python ortamında geliştirme, hata ayıklama ve özelleştirme içindir. [Python kılavuzu](../installation/python.md).

`local-shell-mcp` development/debugging veya Python-based environment daha kolay yönetiliyorsa **`pipx` veya source install** kullanın.

Yalnız server process spawn edebilen local MCP client’lar için **stdio mode** kullanın. Public deployment değildir ve ChatGPT web/app tarafından doğrudan kullanılamaz.

## Public endpoint kuralı

Gemini ve ChatGPT gibi harici HTTP MCP istemcileri için MCP uç noktası şöyledir:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` yalnız origin’dir:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` sonuna `/mcp` eklemeyin.

## Runtime sayfaları

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Client sayfaları

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
