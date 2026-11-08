<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# Birleşik web çalışma alanı

**Birleşik LSM web çalışma alanı**, local-shell-mcp'yi günlük olarak kullanmanın önerilen yoludur. Yapay zeka sohbetini, proje geçmişini ve LSM kontrol düzlemini değiştirilmiş, satıcı tarafından sunulan LibreChat ön ucunu temel alan tek bir duyarlı arayüzde birleştirir. [ChatGPT](chatgpt-connector.md) veya [Gemini](gemini-spark.md) gibi harici MCP istemcilerini hâlâ bağlayabilirsiniz.

Çalışma alanı **kendi kendine barındırılır ve kurulumu isteğe bağlıdır**: ayrı bir web hizmetidir; minimum Denetleyici görüntüsünün, bağımsız yürütülebilir dosyanın veya uzak Çalışan paketinin parçası değildir. Yalnızca denetleyici dağıtımları orijinal tarayıcı kullanıcı arayüzünü ve OpenTUI'yi korur.

## Çalışma alanında neler var?

| Alan | Ne yapabilirsin |
|---|---|
| Sohbet ve projeler | Yapılandırılmış bir model seçin, konuşmalar oluşturun, projeleri düzenleyin, geçmiş sohbetleri bulun ve konuşmaları arşivleyin. Geçmiş sunucuda kalır. |
| Denetleyiciye genel bakış | Sağlığı, son etkinlikleri ve bağlı makineleri görüntüleyin. |
| Dosyalar | Yerel veya uzak dosyalara göz atın ve yönetin. |
| Terminaller | Denetleyici veya İşçilerdeki kalıcı terminallerle çalışın. |
| Masaüstü | Uzak GUI oturumlarını inceleyin ve kontrol edin. |
| Oturumlar | Dayanıklı LSM görevlerini ve bunların yaşam döngüsünü inceleyin. |
| Uzaktan kumandalar | Giden İşçileri bağlayın ve yönetin. |
| Denetim | Model kaynaklı araç etkinliğini inceleyin. |
| İç içe MCP | LSM'nin arkasındaki harici MCP sunucularını kaydedin, düzenleyin, etkinleştirin, devre dışı bırakın, yenileyin ve kaldırın. |

Denetleyici rotaları `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` ve `/control/audit`'dir. Sohbet `/c/new`'de açılır. LSM MCP yöneticisi **LSM'nin iç içe MCP kaydını** kontrol eder; LibreChat'te ikinci bir kayıt defteri oluşturmaz.

## İsteğe bağlı sohbet yığınını dağıtın

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

## Oturum açın ve sohbeti kullanın

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Sohbet yüklemeleri (32 MiB'a kadar) Denetleyici çalışma alanı altında depolanır ve bunların mutlak yolları modele sağlanır. Tarayıcı yüklemeleri ek dosya izinleri vermez. Modele yönelik araç çağrıları, LSM yetkilendirmesi, denetimi ve uzak çalışan yönlendiricisinden geçer.

## Harici MCP, güvenlik ve veriler

Yuvalanmış harici MCP sunucularını yönetmek için çalışma alanı MCP kenar çubuğunu kullanın. Bu, ayrı özel ortam değişkenleri ve istek başlıkları dahil olmak üzere yerel stdio sunucularını ve HTTP sunucularını destekler. Sırlar tarayıcıya döndürülmez. **Harici MCP** sohbet düğmesi, iç içe geçmiş araçların aranmasına, incelenmesine ve çağrılmasına olanak tanır; yerel LSM araçları devre dışı bırakıldığında `mcp_manage` modelini vermez. Kullanıcı arayüzü yönetimi normal Denetleyici yetkilendirmesi ile korunur.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Sorun giderme

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Uygulama ayrıntıları ve güncellemeleri için [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) ve [human interface guide](../guides/human-interface.md)'e bakın.
