<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Uzak workers

Remote workers, `local-shell-mcp`’nin dışarıya HTTP(S) isteği gönderebilen ancak gelen SSH bağlantısı kabul edemeyen makineleri kontrol etmesini sağlar.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Temel workflow

1. `remote_manage(action="invite", ...)` ile davet oluşturun.
2. Oluşturulan komutu uzak makinede çalıştırın.
3. `remote_manage(action="list")` ile kaydı doğrulayın.
4. `machine="<worker-name>"` ile normal araçları çağırın; örneğin `environment_get`, `run_shell`, `file_read` veya `browser_run_script`.
5. `remote_transfer` ile izlenen controller-to-worker, worker-to-controller veya worker-to-worker dosya/dizin aktarımı başlatın. `job_list` ya da `job_tail` ile takip edin; `job_stop` veya `job_retry` ile durdurun ya da yeniden deneyin.
6. `remote_manage(action="rename", ...)` veya `remote_manage(action="revoke", ...)` ile worker’ı yeniden adlandırın veya iptal edin.

Yalnızca worker yönetimi `remote_*` adlarını kullanır. Execution, shell, job, filesystem, patch ve browser işlemleri local ve remote aynı schema’yı paylaşır. Machine vermek ayrıca `remote:use` OAuth scope gerektirir.

## Kalıcı workers

Davet sonucu platforma özel komutlar içerir:

- `persistent_command` Linux/macOS üzerinde user service kurup başlatır.
- `powershell_persistent_command` PowerShell üzerinden Windows user task kurup başlatır.

Windows’ta `local-shell-mcp worker install-service`, mevcut kullanıcı için `local-shell-mcp-worker` görevini kaydeder. Hemen başlar, reboot sonrasında bu kullanıcı giriş yaptığında yeniden başlar, pilde çalışmaya izin verir, yinelenen başlatmaları yok sayar ve başarısız çalışmaları yeniden dener. Administrator yetkisi gerektirmez ve kullanıcı giriş yapmadan önce çalışmaz.

Her platformda aynı lifecycle commands kullanılır:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

Worker log, worker state directory altında `worker.log` olarak saklanır.

## Yetenekler

Workers shell/persistent shell sessions, tracked jobs, filesystem operations, transfer internals, Python execution, patches ve bağımlılıklar kuruluysa Playwright destekler. Git, `run_shell(machine=...)` üzerinden standart komutları kullanır.

## Güvenlik ve sürümleme

Bağlanan worker, MCP client’a yapılandırılmış ortam üzerinde kontrol verir. Kısa invite TTL, özel work directory/account kullanın, audit log’ları inceleyin ve görev sonrasında worker’ı revoke edin. Oluşturulan davet control server sürümüyle eşleşen worker code kurar.

## Sorun giderme

Worker görünmüyorsa outbound HTTPS access, public base URL erişilebilirliği, invite expiry, system time ve control-server log’larını kontrol edin.
