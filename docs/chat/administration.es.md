<!-- i18n-source-sha256: 91fa7e8e41354be2761864ffe05d1efb85063953c79a40065ad61661cc15b836 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Administración y resolución de problemas.

## Arquitectura de implementación.

La interfaz de usuario web se encuentra alojada en el controlador Python, en el mismo origen que sus puntos finales REST y MCP. El servidor de estado predeterminado es SQLite. Los binarios y archivos necesarios para su uso incluyen los recursos compilados del frontend. Para construir el frontend desde la fuente, se requiere el conjunto de herramientas de desarrollo JavaScript, y no se necesita ejecutar el controlador instalado. No se requieren Node.js, MongoDB, Meilisearch ni ningún otro backend adicional para su funcionamiento.

Utilice las instrucciones de inicio rápido y las referencias de configuración disponibles en los archivos [Quickstart](../getting-started/quickstart.md) y [Configuration reference](../reference/configuration.md). Para la construcción desde el código fuente, consulte las instrucciones de construcción de la interfaz web en [WebUI build instructions](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## Asegúrese de que la implementación sea segura.

Utilice un proxy inverso HTTPS de confianza, o bien un túnel de comunicación seguro. Asegúrese de que el Controller se encuentre dentro de un contenedor o máquina virtual adecuada. Limite el acceso entrante y proteja las credenciales de salida. No exponga ningún punto de ejecución no autenticado en la red pública de Internet.

El proxy debe soportar la transmisión de respuestas sin necesidad de almacenarlas en memoria hasta que se complete la transmisión. Además, debe permitir la actualización de interfaces WebSocket cuando sea necesario. Use tiempos de espera adecuados para las solicitudes de modelos y herramientas, y permita los tamaños de archivos de carga deseados. Mantenga la URL pública configurada consistente con el origen del navegador y los llamados OAuth. No corrija fallos de TLS desactivando globalmente las comprobaciones de certificados.

Las solicitudes modelo se originan en el Controller. Los mensajes visibles para el modelo, los archivos adjuntos y los resultados obtenidos por medio de herramientas específicas pueden ser enviados a la API correspondiente. Es importante evaluar los términos relacionados con el manejo de datos del proveedor antes de utilizar contenido confidencial. También es necesario proteger las claves externas del MCP y las tokens de invitación utilizados por el Worker.

## Estado, respaldo y actualizaciones

El directorio de estado predeterminado es `.local-shell-mcp`, que se encuentra dentro del espacio de trabajo configurado. El valor `LOCAL_SHELL_MCP_STATE_DIR` puede cambiar este directorio. La base de datos compartida es `lsm.sqlite3`. Los chats, proyectos, configuraciones, agentes, memoria, horarios y estado de ejecución se almacenan en el servidor. En cambio, los archivos adjuntos, los archivos del espacio de trabajo y otros datos pueden estar fuera de la base de datos.

Realice copias de seguridad del directorio estatal completo, así como de los datos configurables que se encuentran fuera de ese directorio. También haga copias de seguridad del entorno de implementación y de los archivos relevantes del área de trabajo. Considere las copias de seguridad como algo delicado. Una copia de seguridad únicamente basada en la base de datos puede omitir los archivos adjuntos y la configuración relacionada. Utilice un controlador en estado de inactividad o un mecanismo de copia de seguridad consistente con SQLite. Copiar únicamente el archivo principal de la base de datos SQLite activa puede evitar que se copien los contenidos WAL. Verifique las copias de seguridad restaurando los datos en una implementación de prueba aislada.

Antes de realizar la actualización, registre la versión actual del sistema, la ruta de ejecución, la configuración, la ubicación del estado y las tareas activas. Detenga o elimine de manera segura las tareas en ejecución. Realice una copia de seguridad consistente del sistema. Luego, actualice la instalación y verifique la autenticación, el historial de chat, la generación de modelos, el streaming, los trabajadores y las tareas programadas. La migración a SQLite desde el estado anterior es posible al inicio del sistema. Preserve los archivos antiguos hasta que se haya verificado la migración. No reemplezque el directorio de datos de producción por uno vacío de prueba.

El rollback no consiste simplemente en cambiar el estado binario de los datos, si una migración de base de datos ha alterado ese estado. Es necesario restaurar el estado compatible cuando sea necesario, y evitar ejecutar dos controladores configurados de forma independiente en el mismo almacenamiento activo.

## El diagnóstico indica que el chat no funcionó.

| Síntoma | Primero, verifique. |
|---|---|
| No se puede cargar la interfaz de usuario. | Proceso de Controller, paquete de front-end, URL correcta, proxy y autenticación |
| El modelo no está disponible. | Configuración del canal, detección de modelos, identificación del modelo, autorización de la cuenta |
| Respuesta HTTP 401/403 del proveedor | Clave de API/ cuenta, permisos del proveedor, canal y protocolo seleccionados |
| HTTP 429 | Límites de tarifa/cuotas hacia el flujo de datos en dirección contraria, solicitudes simultáneas, estado del cuenta/plan |
| HTTP 400/413/422 | Se solicita información sobre la compatibilidad con otros dispositivos, el tamaño de los datos de entrada/contexto, los límites de archivos adjuntos, y los parámetros del modelo. |
| Error de tipo 5xx en HTTP o tiempo de espera excesivo. | Estado del proveedor, red, capacidad de servicio del modelo, tiempos de espera en el proxy. |
| La transmisión de datos se detiene. | Reconnect/reload: se debe inspeccionar el estado de generación y los errores detallados. |
| La herramienta no está disponible. | Funciones disponibles: capacidades del agente, lista de acceso de la máquina, ámbitos de OAuth, conmutadores del controlador. |
| El trabajador está fuera de línea. | Registro de trabajadores, conexiones de salida, registros de heartbeat y registros del Controller. |
| Pendiente de aprobación/preguntas. | Se puede abrir la conversación e inspeccionar la acción solicitada. |
| El cronograma no se ejecuta. | Estado habilitado, zona horaria, agente/ canal, destino, autorización guardada, última ejecución |

No asuma que todos los errores HTTP provienen del mismo servicio. Es necesario distinguir entre un fallo en el inicio de sesión LSM, un error en la API de modelo upstream, un error externo relacionado con MCP y un error en el transporte de trabajo. Verifique los errores detallados y los registros relevantes del controlador. Deje fuera los datos de acceso, las tokens de portadora y las URL de llamada de retorno antes de compartirlos.

## Intentos de reanudación y recuperación por parte del proveedor

Antes de que comience la respuesta del modelo, los errores transitorios de conexión y ciertos errores HTTP (408, 429, 500, 502, 503, 504) pueden reintentarse con esperas acotadas. Las esperas ordinarias actuales son de 1, 2, 4, 8, 16, 30, 30 y 30 segundos (ocho reintentos tras la solicitud inicial). HTTP Retry-After puede ampliar una espera hasta 120 segundos; ciertos errores de streaming añaden variación aleatoria. El límite de reintentos se aplica a cada solicitud al modelo, no a toda la conversación. La compactación tiene su propio mecanismo de recuperación. Un límite de tasa por créditos agotados puede persistir hasta que el proveedor reponga la cuota. Los reintentos automáticos no garantizan el éxito ni convierten una suscripción en ilimitada.

La interrupción durante el proceso de ejecución es diferente de un error que ocurre antes del primer evento de respuesta. No se debe confiar en la reproducción automática de una secuencia de herramientas que ya se ha ejecutado parcialmente. Es necesario verificar el historial guardado y el estado externo antes de intentar nuevamente. Si la ejecución sigue activa, se debe volver a conectarse, en lugar de iniciar un trabajo duplicado. Si la ejecución terminó con un error, se deben utilizar los controles de recuperación/retry del chat según sea necesario. De lo contrario, se debe iniciar un nuevo chat con una transferencia explícita de responsabilidades, si el proceso original no puede continuar.

Los errores relacionados con la compresión del contexto deben investigarse por separado de los errores comunes en la generación de modelos. Verifique el límite de memoria efectivo, la compatibilidad entre modelos, los resultados de las herramientas utilizadas y la cuota disponible. Consulte [Memoria y contexto](context.md).

## ¿Qué incluir en un informe de errores?

Indique la versión y el commit del LSM, el método de instalación, el sistema operativo, el modelo del protocolo, el tipo de punto final sancionado, el ID del modelo, la hora aproximada, los pasos necesarios para reproducir el problema, el estado de las conversaciones o ejecuciones relevantes, y los errores detallados. En el caso de problemas remotos, indique también la versión del Worker, el nombre de la máquina y el estado de los Heartbeat/Polls. Incluya, si es posible, una pequeña demostración del problema; nunca envíe claves de API, tokens OAuth, prompts privados o datos personales innecesarios.
