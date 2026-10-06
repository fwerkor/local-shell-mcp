<!-- i18n-source-sha256: f471795a57e16e999999f856000b779183d5b6c642ffc8c852c77e7faf3bc0dd -->
# Patrones de uso y guía de prompting

`local-shell-mcp` expone herramientas potentes. Los buenos resultados dependen de pedir al modelo que inspeccione primero, actúe en pasos pequeños, verifique y reporte qué cambió.

## Bucle operativo general

Use este bucle para la mayoría de tareas de código:

1. Inspeccionar: `environment_get`, `file_tree`, `file_grep`, `file_read` y `run_shell` para comandos como `git status`.
2. Planificar: pedir al modelo que identifique los archivos y tests mínimos implicados.
3. Editar: usar `file_edit`, `file_patch` o comandos shell.
4. Verificar: ejecutar tests/builds dirigidos con `run_shell` o shells persistentes.
5. Revisar: ejecutar `git diff` mediante `run_shell` y usar `secret_scan` y `audit_tail` cuando corresponda.
6. Commit/exportar: usar comandos Git CLI explícitos mediante `run_shell` o `link_create`.

## Elección de herramientas

| Tarea | Preferir | Evitar |
|---|---|---|
| Comando one-shot rápido | `run_shell` | Iniciar un shell persistente para cada comando |
| Dev server, REPL o watch task largo | `shell_start` + `shell_read` + `shell_send` | Bloquear `run_shell` hasta timeout |
| Análisis estructurado o generación de archivos | `run_python` | Pipelines shell frágiles para JSON/texto complejo |
| Edición exacta pequeña | `file_edit` | Reescribir archivos completos sin necesidad |
| Una o varias sustituciones en un archivo | `file_edit` with an `edits` array | Repetir edits obsoletos sin releer |
| Patch multiarchivo | `file_patch` | Edits shell ad hoc |
| Buscar archivos | `file_tree`, `file_glob` | Listados recursivos completos de repositorios grandes |
| Buscar código | `file_grep` | Leer muchos archivos a ciegas |
| Evidencia de navegador | `browser_snapshot`, `browser_run_script` | Adivinar por nombres de página o rutas |
| Artefactos descargables | `link_create` | Pegar contenido binario grande en chat |
| Trabajo en máquina remota | normal tools with `machine`, plus `remote_transfer` | Abrir SSH entrante cuando outbound worker basta |

## Llamar herramientas desde la CLI

Para scripts de shell y CI, `lsm call <tool>` invoca la misma superficie de herramientas registradas a través del controller loopback en ejecución, por lo que se conservan los remote workers y el estado del controller.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Usa `--session s_...` para asociar la llamada a una Logical Session. Con Docker Compose puedes ejecutarlo desde la raíz del repositorio, donde la CLI detecta la ruta compartida del token por defecto, o pasar `--token-file <path>` si el controller usa otro sistema de archivos de runtime. `--direct` omite el controller y solo funciona de forma local.

## Plantillas de prompt

### Orientación read-only del repository

```text
Usa local-shell-mcp. Inspecciona el layout del repository y git status. No modifiques archivos. Resume los componentes principales, comandos de test que puedas inferir y riesgos obvios antes de cambiar nada.
```

### Corrección focalizada de bug

```text
Usa local-shell-mcp para corregir el bug. Primero reprodúcelo o localízalo con el comando relevante más pequeño. Lee los archivos antes de editar. Haz un patch mínimo, ejecuta la verificación dirigida y luego muestra git diff y los tests exactos ejecutados. No hagas commit hasta que lo apruebe.
```

### Workflow de commit y push

```text
Usa local-shell-mcp. Comprueba git status y diff, ejecuta los tests relevantes y secret_scan, crea un commit focalizado con mensaje conciso y luego haz push de la branch actual. No incluyas cachés, artefactos de build ni formatting no relacionado.
```

### Proceso de larga duración

```text
Inicia el dev server en una persistent shell session, lee el output hasta que esté ready y después usa browser tools para verificar la página. Conserva el session id y termina la sesión después de verificar.
```

### Tarea en remote worker

```text
Usa el remote worker conectado llamado <machine>. Primero llama environment_get con machine=<machine> y luego file_list con la misma machine. Trabaja solo dentro del remote workdir configurado. Usa run_shell para comandos cortos y shell_start o job_start para trabajo largo.
```

## Trabajo con repositories

Secuencia recomendada para cambios open-source:

1. Ejecutar `git status --short --branch` mediante `run_shell`.
2. Hacer fetch e inspeccionar branches con Git CLI explícito cuando importe upstream state.
3. Usar `file_grep` y `file_read` antes de editar.
4. Hacer un patch mínimo.
5. Ejecutar primero tests dirigidos y luego tests más amplios cuando sea práctico.
6. Ejecutar `secret_scan` antes de commit o push.
7. Stage y commit explícitos con un mensaje conciso.

Pida un commit por cambio lógico cuando los maintainers necesiten un historial fácil de revisar.

## Trabajo con artefactos generados

Para PDFs, reports, screenshots, archives o logs:

1. Generar el archivo dentro del workspace.
2. Verificar que existe y tiene el tamaño esperado.
3. Usar `link_create` con TTL corto y `max_downloads` opcional.
4. Revocar el link cuando ya no sea necesario.

No cree links públicos para private keys, credential directories ni datos personales no relacionados.

## Trabajo con máquinas remotas

Remote worker mode sirve cuando una máquina puede hacer peticiones HTTPS salientes pero no aceptar SSH entrante.

Buenas prácticas:

- Crear o renombrar máquinas con `remote_manage(action="invite", ...)` o `remote_manage(action="rename", ...)`.
- Llamar `environment_get(machine=...)` antes de actuar.
- Usar `remote_transfer` para iniciar transfer jobs controller/worker o worker/worker y gestionarlos con las herramientas `job_*` normales.
- Revocar workers tras la tarea con `remote_manage(action="revoke", ...)`.

## Anti-patterns

Evite estas instrucciones salvo que el entorno sea desechable y entienda las consecuencias:

- “Instala globalmente lo que haga falta” en un server lanzado en host.
- “Ejecuta hasta que funcione” sin límites de tiempo ni criterios de verificación.
- “Haz commit de todo” en un repository con artefactos generados.
- “Expón todo el home directory” por comodidad.
- “Crea un file link para todo el workspace”.
- Ejecutar deployments públicos con `LOCAL_SHELL_MCP_AUTH_MODE=none`.
