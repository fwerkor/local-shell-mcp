<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Workers remotos

Los remote workers permiten que `local-shell-mcp` controle máquinas que pueden realizar solicitudes HTTP(S) salientes pero no aceptar conexiones SSH entrantes.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Flujo básico

1. Cree una invitación con `remote_manage(action="invite", ...)`.
2. Ejecute el comando generado en la máquina remota.
3. Confirme el registro con `remote_manage(action="list")`.
4. Llame a herramientas normales con `machine="<worker-name>"`, por ejemplo `environment_get`, `run_shell`, `file_read` o `browser_run_script`.
5. Use `remote_transfer` para iniciar una transferencia rastreada controller-to-worker, worker-to-controller o worker-to-worker de archivos o directorios. Siga con `job_list` o `job_tail`; detenga o reintente con `job_stop` o `job_retry`.
6. Cambie el nombre o revoque workers con `remote_manage(action="rename", ...)` o `remote_manage(action="revoke", ...)`.

De forma predeterminada, cada invitación registra un solo worker (`max_uses=1`). Aumente `max_uses` para registrar varios workers con la misma invitación. Deje `name` vacío si la invitación se usa varias veces. El parámetro opcional `ttl_s` tiene un valor predeterminado de dos horas (7200 segundos) y un máximo de siete días (604800 segundos).

Solo la administración de workers usa nombres `remote_*`. Las operaciones de execution, shell, job, filesystem, patch y browser comparten el mismo schema local y remotamente. Especificar una machine requiere además el OAuth scope `remote:use`.

## Workers persistentes

El resultado de la invitación contiene comandos específicos de plataforma:

- `persistent_command` instala e inicia un servicio de usuario en Linux o macOS.
- `powershell_persistent_command` instala e inicia una tarea de usuario de Windows desde PowerShell.

En Windows, `local-shell-mcp worker install-service` registra la tarea `local-shell-mcp-worker` para el usuario actual. Se inicia de inmediato, vuelve a iniciarse cuando ese usuario inicia sesión después de reiniciar, permite funcionar con batería, ignora inicios duplicados y reintenta ejecuciones fallidas. No requiere permisos de administrador y no se ejecuta antes de que el usuario inicie sesión.

Use los mismos comandos de lifecycle en todas las plataformas:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

El log del worker se almacena como `worker.log` bajo el worker state directory.

## Capacidades

Los workers admiten shell y persistent shell sessions, tracked jobs, operaciones filesystem, transfer internals, ejecución Python, patches y Playwright donde estén instaladas las dependencias. Git usa comandos estándar mediante `run_shell(machine=...)`.

## Seguridad y versionado

Un worker unido da al MCP client control sobre su entorno configurado. Use invite TTL cortos, work directories o cuentas dedicadas, revise audit logs y revoque los workers al finalizar. La invitación generada instala código de worker que coincide con la versión del control server.

## Solución de problemas

Si un worker no aparece, compruebe el acceso HTTPS saliente, la accesibilidad del public base URL, la expiración de la invitación, la hora del sistema y los logs del control server.
