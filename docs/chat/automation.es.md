<!-- i18n-source-sha256: 01c14c19cf5addf99299993b57542259bcb40bbfb13600758b516a86c89e716b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Objetivos, charlas programadas y tareas que requieren tiempo para su ejecución

## Elija el mecanismo adecuado.

| Mecanismo | Propósito |
|---|---|
| Generación de chats normales. | Respuesta al prompt actual, incluyendo llamadas a herramientas. |
| Objetivos del chat. | Continuación de una sesión lógica activa, sin importar los límites de turnos del modelo. |
| Chat programado. | Inicie un agent con un prompt guardado, de forma periódica. |
| Tareas persistentes o terminales. | Ejecución de comandos independientemente de una solicitud individual del modelo. |
| Subagentes. | Asignar una tarea limitada a otro hilo de Agent. |

Un chat programado no es un trabajo que se ejecuta de forma continua. Una sesión lógica, por su parte, no constituye una conversación ni un proceso del sistema operativo. Cancelar una sesión no implica necesariamente la terminación de todo lo que se inició con los herramientas utilizadas para gestionar dicha sesión.

## Objetivos del chat.

Para tareas que requieren mucho tiempo, pídale al agente que defina un objetivo concreto y que mantenga un plan detallado, utilizando las herramientas de sesión lógica. El plan registra los pasos a seguir y el estado de cada uno de ellos. La ejecución del chat puede continuar con el plan activo, sin necesidad de esperar a que aparezca un nuevo usuario o a que pase el tiempo de inactividad del MCP Live Workspace.

Revisar el plan y los progresos realizados. Puede detener, continuar o cancelar la ejecución utilizando los controles disponibles para cada objetivo. La continuación requiere que el plan esté activo y que la ejecución sea válida; no se debe continuar con un plan ya completado, bloqueado o cancelado. Las respuestas repetitivas sin progreso generan una pausa en lugar de un bucle infinito (actualmente, esto ocurre después de tres límites sin cambios). Resolver el problema que impide la continuación es necesario antes de reanudar la ejecución.

Defina los criterios de completación. Por ejemplo: inspeccionar un repositorio, implementar las correcciones necesarias, ejecutar el conjunto de pruebas correspondientes y reportar cualquier fallo que ocurra. Pida al agente que registre los IDs de las commits y los resultados de las pruebas, en lugar de declarar el éxito únicamente basándose en su propio plan.

El mecanismo de objetivos del cliente externo MCP es independiente. Para obtener más información sobre el flujo de trabajo relacionado con la transferencia de sesión lógica y espacio de trabajo en vivo, consulte [Interfaz humano](../guides/human-interface.md).

## Crear un chat programado.

![Barra lateral de chats programados con un ejemplo desactivado](../assets/chat/scheduled-chats.png)

Abra la gestión de chat programado. Cree un horario con un nombre descriptivo, un agente guardado, un prompt, la zona horaria y la frecuencia de las conversaciones. Elija el objetivo de la conversación; opcionalmente, seleccione un proyecto para iniciar una nueva conversación. Guarde y active el horario. Utilice el control de ejecución manual para validar la configuración antes de utilizarlo.

Las pautas de ejecución compatibles incluyen horarios diarios, semanales, cronogramas de cinco campos, y ejecución continua. La ejecución continua comienza en el momento en que se producen los eventos después del tiempo de retraso configurado; un retraso nulo puede causar una carga continua en el proveedor y en la máquina. Los horarios recurrentes ordinarios requieren que haya un intervalo mínimo de cinco minutos entre cada ejecución. Se recomienda utilizar un huso horario específico de IANA, como `Asia/Shanghai` o `UTC`. Consulte el resultado de la próxima ejecución después de guardar los ajustes.

Ejemplo de cron a las 09:00 los días laborables:

```text
0 9 * * 1-5
```

Esto utiliza el huso horario seleccionado, pero no necesariamente el huso horario del sistema del controlador. Consulte las transiciones relacionadas con el horario de verano si el huso horario elegido lo aplica.

## Objetivos de la conversación

- **Nueva conversación en cada ejecución:** es recomendable iniciar una conversación separada para cada ocurrencia; esto es útil cuando se trata de informes independientes.
- **Reutilizar una conversación:** Se puede crear una conversación en la primera ocasión y reutilizarla para futuras situaciones similares. Esto es útil para el monitoreo continuo de las actividades.
- **Usar una conversación existente:** Elija una conversación ya existente que recibirá turnos programados para sus participantes.

Una conversación que ya se ha utilizado o que existe de forma independiente puede crecer y requerir una organización más eficiente. Se recomienda utilizar chats independientes cuando el contexto histórico no sea necesario. Las ejecuciones programadas dependen de si el agente seleccionado y el canal de modelado todavía están disponibles y son útiles para el uso.

## Permisos no supervisados

La ejecución programada pertenece al Controller y utiliza los nombres de los ámbitos autorizados guardados, en vez de conservar un token de inicio de sesión del navegador. Guarde o ejecute manualmente una programación para autorizarla cuando sea necesario. Se aplican los permisos de máquina del Agent designado; las excepciones ordinarias de máquina del proyecto o de la conversación no constituyen la política de máquina de la programación. Siguen aplicándose las restricciones del Controller, la autorización guardada, las capacidades y la aprobación de herramientas.

Para servidores MCP externos que requieren autenticación, un inicio de sesión interactivo no implica automáticamente una autorización renovable para ejecución desatendida. Si la interfaz de programación indica que se necesita volver a autenticar o permitir acceso desatendido, resuelva las credenciales específicas del servidor o elimine esa dependencia antes de habilitar la programación. No reutilice tokens del navegador como sustituto.

Se debe utilizar un agente de solo lectura para el monitoreo. Se deben describir explícitamente los objetivos permitidos, los resultados deseados y las acciones que se deben evitar. Si una tarea programada requiere intervención humana o aprobación, es necesario inspeccionar las interacciones pendientes. No se debe asumir que la ejecución sin supervisión implica un acceso ilimitado. Ejemplo de un mensaje de monitoreo:

```text
Verifique el trabajo de entrenamiento especificado, así como los registros relacionados con ese trabajo.
Informe sobre el paso actual, las pérdidas, el caudal de datos, el tiempo estimado para la entrega y cualquier error nuevo que pueda surgir.
No modifique los archivos, no reinicie la tarea ni lance nuevos trabajos.
Si los datos no están disponibles, indique el motivo exacto por el cual no se pueden obtener.
```

## Ciclo de vida y recuperación

El controlador mantiene los horarios de ejecución y las transacciones relacionadas con los eventos que ocurren durante el proceso de ejecución, con el objetivo de evitar que se produzcan duplicaciones en los inicios del proceso. No es necesario que una pestaña del navegador permanezca abierta. No se debe asumir que los eventos que se han perdido siempre se reproducirán, ni que todo el trabajo externo se mantendrá activo después de un reinicio del controlador. Es importante verificar el último ejecución, la próxima ejecución, las operaciones en curso y las conversaciones asociadas después de un período de inactividad.

Desactive los horarios de ejecución para evitar que se produzcan automáticamente en el futuro. Se debe inspeccionar cada uno de los eventos que ya están en ejecución por separado. Detener la programación no garantiza que la generación o el trabajo en sí se cancelen. Elimine los horarios que ya no se necesitan y revoque los permisos del agente que no son necesarios.

Un trabajo o terminal creado por un agente WebUI puede continuar funcionando incluso después de que se complete la respuesta al modelo. Un reinicio del controlador no necesariamente termina ese trabajo. Una cancelación explícita, la pérdida de permisos de la máquina o la expiración de los permisos pueden causar la cancelación de los trabajos realizados por el agente. Si el trabajador está fuera de línea, la cancelación puede permanecer pendiente hasta que pueda ser entregado. Es necesario inspeccionar el trabajo o terminal en sí antes de declarar que la ejecución ha terminado. El agente solo puede enviar o detener los trabajos/shells creados por él a través del camino de herramientas protegido de WebUI. Los clientes MCP externos conservan su semántica nativa.

Las herramientas de fondo del agente y las tareas subagentes tienen su propio ciclo de vida. Un resultado puede estar pendiente de entrega, incluso después de que la ejecución haya terminado. Es necesario verificar el panel de tareas de fondo de la conversación y recopilar el resultado correspondiente. No se debe iniciar una tarea duplicada simplemente porque el resultado aún no está visible.

Para comandos que deben durar más allá de una solicitud individual de herramienta, utilice trabajos rastreados por LSM o terminales persistentes. Guarde el resultado en un archivo de registro, anote los identificadores de los trabajos y verifique el progreso real. Consulte [Patrones de uso](../guides/usage-patterns.md).
