<!-- i18n-source-sha256: e5ebd5f8cfb42332f4e38d63eabe47a6274ceacf919130202203bd85917f3469 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Herramientas, máquinas y permisos.

## Capas de autorización.

El hecho de que un herramienta esté en la lista no garantiza que se pueda ejecutarla. La autorización efectiva implica la combinación de restricciones del controlador, ámbitos del principal autenticado, políticas de la máquina, capacidades del agente y aprobación de la herramienta. Las instrucciones claras por sí solas no son suficientes para garantizar el acceso a la herramienta.

Las máquinas registradas, incluyendo el objetivo local del controlador cuando está activado, tienen por defecto la capacidad de leer y escribir en la política de chat. Se recomienda restringir estos valores en casos de implementaciones sensibles. Los nombres de las máquinas desconocidas no reciben ningún tipo de autorización implícita. El controlador puede desactivar la ejecución local o los trabajadores remotos de forma independiente.

## Acceso a la máquina

| Acceso | Significado |
|---|---|
| Ninguno | Las operaciones relacionadas con la máquina no están disponibles. |
| Sólo lectura | Solo se permiten las operaciones clasificadas como de solo lectura; la ejecución de scripts o programas en Python no es una operación de solo lectura. |
| Leer/escribir | Se permiten las operaciones de lectura, modificación y ejecución autorizadas, pero con otros límites aplicables. |
| Heredar | Se utiliza el valor predeterminado correspondiente, en lugar de un valor específico que se sobrepase. |

![Permisos y modo de aprobación de la máquina en una conversación](../assets/chat/machine-permissions.png)

Establezca los valores globales y las excepciones por proyecto y conversación en los controles de permisos de máquina. Las excepciones de una conversación tienen prioridad sobre las del proyecto, y estas sobre los valores globales. Un Agent puede limitar aún más el acceso por máquina o mediante su política predeterminada; sus permisos explícitos no eluden las restricciones del principal autenticado ni del Controller.

Ejemplo: una política global de lectura y escritura, una excepción del proyecto de solo lectura y un Agent con permiso de lectura y escritura producen acceso de solo lectura en la conversación del proyecto, salvo que la política de la conversación lo anule explícitamente. Una excepción de lectura y escritura de la conversación tampoco puede superar el límite de solo lectura del Agent.

Una ejecución programada con un agente específico utiliza la política de máquina de ese agente, así como los ámbitos de ejecución guardados, en lugar de heredar las configuraciones de la máquina de chat normal. Ver [Objetivos y automatización](automation.md). Utilice un agente dedicado para tareas que no requieren supervisión constante.

## Aprobación de herramientas

| Moda | Comportamiento |
|---|---|
| Automático | Las llamadas realizadas con herramientas autorizadas se procesan sin necesidad de una solicitud adicional de aprobación, a menos que una política específica lo requiera. |
| Revisar operaciones riesgosas | El controlador solicita una revisión de las operaciones que se clasifican como peligrosas. Esto incluye comandos shell arbitrarios y muchas llamadas externas. |
| Revisar todas las herramientas | Se solicita la aprobación para las llamadas a herramientas comunes. |

La configuración de aprobación de la conversación puede heredar los valores del Agent y los globales. Las reglas explícitas de denegación o aprobación siguen siendo aplicables. Un Agent hijo no puede debilitar el modo de aprobación de su padre. La aprobación es independiente de los permisos: aprobar una acción de máquina denegada no concede acceso a ella.

Revisen los argumentos reales, el destino y los posibles efectos secundarios antes de aprobarlo. En un flujo de trabajo sin supervisión, es necesario configurar cuidadosamente al agente y las políticas de aprobación. La necesidad de una aprobación humana puede retrasar el progreso. No amplíen el acceso simplemente para eliminar los mensajes de alerta.

## Herramientas MCP nativas y externas

Las herramientas nativas operan sobre el Controller y los Workers registrados, a través de LSM. El registro de herramientas incluye operaciones con archivos, shell y tareas, operaciones en navegadores y interfaces gráficas, descubrimiento remoto, sesiones lógicas y otras funciones. Para conocer los esquemas de argumentos exactos, consulte [Referencia de herramientas](../reference/tools.md). Para información sobre cómo conectar máquinas, vea [Trabajadores remotos](../guides/remote-workers.md).

Gestione los servidores MCP anidados en la interfaz WebUI. Las configuraciones admitidas incluyen el uso de transporte local en stdio y transporte remoto a través de HTTP. También se pueden utilizar variables de entorno o encabezados específicos para cada servidor. Habilitar la capacidad de MCP externo en el chat y en el agente correspondiente. El agente puede descubrir, inspeccionar y llamar a las herramientas externas disponibles; su autorización y aprobación siguen aplicándose.

Una herramienta MCP externa puede operar independientemente de las ACL de máquinas nativas: una API externa remota puede modificar recursos incluso cuando el acceso a máquinas locales está deshabilitado. Revise por separado los permisos y las credenciales del servicio externo. No instale servidores stdio no confiables en un Controller que contenga archivos sensibles.

## Pregunte al usuario y a las opciones de activación/desactivación de funcionalidades.

“Ask User” permite que el agente solicite información de forma estructurada, en lugar de hacer suposiciones. Se responde utilizando el control de preguntas presentado. Se trata de una solicitud de información, no de permiso para evitar un proceso que ha sido denegado. Cuando la tarea se queda sin supervisión, se debe indicar al agente cómo manejar las situaciones inciertas y examinar las interacciones pendientes antes de considerar que la tarea está completada.

El compositor explica los controles relacionados con las características del modelo, como la búsqueda en red, el MCP externo y la memoria. Estos controles determinan qué capacidades están disponibles para el modelo. Estos controles son independientes de los aspectos relacionados con la autorización; por lo tanto, desactivar una función no elimina los resultados históricos obtenidos. La búsqueda en red está activada por defecto y utiliza herramientas web de solo lectura, como se describe en [Búsqueda en red](../guides/webui-network-search.md).

## Auditoría y verificación

Revisar las llamadas a las herramientas y los resultados obtenidos en el chat; expandir los detalles cuando se diagnostique algún error. El registro de auditoría del controlador muestra la actividad de las herramientas nativas, y las tareas o sesiones revelan cómo se lleva a cabo la ejecución de las mismas. Un resultado exitoso de la API significa que la herramienta devolvió un resultado, pero eso no implica necesariamente que la operación solicitada haya logrado su objetivo. Verificar los datos escritos, el estado de las tareas remotas y la salud del proceso de implementación de forma independiente. Consulte [Registro de auditoría](../guides/audit-log.md).
