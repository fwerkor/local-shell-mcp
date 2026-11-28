<!-- i18n-source-sha256: d33afa60bf803b367c950dbadf80fa77167568a970adcac204cdea7e9e965e45 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Agentes y habilidades

## ¿Cuándo debemos crear un agente?

Un chat directo es útil para preguntas o tareas que se realizan una sola vez. Un “Agent” es una configuración guardada que puede ser seleccionada repetidamente; también puede utilizarse en chats programados o delegarse a otros agentes. Diferentes agentes pueden utilizar canales, modelos, instrucciones y políticas de acceso diferentes. Todos comparten el mismo controlador, pero no necesariamente el mismo alcance de memoria o herramientas.

## Configurar un agente

Gestione el agente desde la interfaz web. Cree un agente, asignele un nombre reconocible y seleccione su modelo. Escriba las instrucciones necesarias para describir la tarea, los resultados deseados, las restricciones y los requisitos de verificación. Configure las capacidades que necesita el agente. Luego, guarde todo y inicie una nueva conversación con él.

![Agent Builder con instrucciones, herramientas, aprobaciones y configuraciones de habilidades](../assets/chat/agent-builder.png)

Por ejemplo, un revisor de repositorios podría tener estas instrucciones:

```text
Revisar los cambios en comparación con la rama principal actual.
Inspeccionar el repositorio y los resultados de las pruebas antes de sacar conclusiones.
No editar archivos, enviar commits ni implementar nada.
Informar sobre los hallazgos concretos, junto con las rutas y las pruebas necesarias para respaldar dichos hallazgos.
```

Las instrucciones son útiles para dirigir el comportamiento del sistema, pero no constituyen una línea de demarcación para la autorización de acceso. Establezca el acceso a la máquina como solo lectura, y omite las capacidades externas innecesarias si el revisor no debe modificar nada. Consulte [Herramientas y permisos](permissions.md).

Es recomendable tener agentes separados para las diferentes tareas, como la revisión de código, la implementación y las operaciones relacionadas con el sistema. Se debe dar a cada agente un acceso mínimo pero suficiente, además de un modelo adecuado para su función. Si un agente no puede comenzar a funcionar, es necesario verificar el canal de comunicación y el modelo utilizado por ese agente antes de cambiar cualquier configuración que no sea relevante.

## Skills

Los paquetes de habilidades contienen instrucciones reutilizables y archivos relacionados, generalmente con una entrada llamada `SKILL.md`. Se pueden gestionar las habilidades desde la interfaz web; se pueden activar las habilidades correspondientes y hacerlas disponibles para el agente o para el chat. El modelo puede descubrir y cargar el contenido de las habilidades cuando sea necesario. Una habilidad puede describir un flujo de trabajo, incluir ejemplos o contener scripts. No se ejecutan automáticamente los scripts, ni se otorgan permisos adicionales a la máquina.

Es necesario verificar las habilidades importadas antes de activarlas. Trate las instrucciones y los archivos relacionados con ellas como cualquier otro código o prompt de terceros. Los nombres y descripciones de las habilidades deben ser lo suficientemente específicos para que el modelo pueda identificarlas fácilmente. Las referencias largas deben mantenerse separadas, y se deben preferir los flujos de trabajo pequeños y independientes. El registro del lado del controlador y las llamadas a herramientas se explican en [Skills](../guides/skills.md).

El contexto automático relacionado con las habilidades y la memoria se graba de forma instantánea, para evitar que sea necesario reescribir el prompt del sistema en cada turno. Los cambios en el alcance de las habilidades pueden tener efecto inmediato; por lo tanto, es recomendable utilizar una nueva conversación al probar el contexto automático recién modificado. Una habilidad cargada de forma intencional es algo diferente del snapshot inicial del contexto automático.

## Delegación y subagentes

Los agentes pueden delegar tareas limitadas a subagentes, siempre que esa capacidad esté disponible. Un subagente puede utilizar un agente configurado y mantener su propia secuencia de ejecución, similar a una conversación. El agente principal coordina la tarea, lee los resultados del subagente y puede continuar con la secuencia de ejecución guardada por el subagente. Es posible inspeccionar las actividades del subagente desde la conversación del agente principal; esa vista no es un chat independiente y editable.

Utilice la delegación para tareas separables, como revisiones independientes, áreas de archivos separadas o investigaciones sobre diferentes hipótesis. Proporcione al subagente un objetivo concreto, un alcance claro y un resultado esperado. Evite escribir en los mismos archivos simultáneamente, a menos que la tarea sea coordinada de forma explícita.

La delegación debe permanecer dentro de los límites de ejecución autorizados por el padre. No se permite el acceso a máquinas o servicios MCP que el padre no pueda utilizar. La política de aprobación del hijo no puede debilitar la política del padre. Las tareas del hijo pueden consumir tokens de modelo y tiempo de forma independiente. Por lo tanto, es necesario inspeccionar su actividad y resultados al evaluar los costos y el progreso.

## Herramientas, acciones y artefactos

El Agent Builder exibe su biblioteca de herramientas disponibles y las opciones de configuración avanzada. Seleccione solo aquellas capacidades que necesite. Para una acción HTTP descrita mediante un esquema OpenAPI, consulte el punto final, los requisitos de autenticación y las operaciones permitidas antes de conectar la acción. Las acciones pueden tener su propia autenticación; una autorización de máquina no autoriza ni revoca las credenciales de una API de terceros. Verifique la respuesta de la acción antes de considerar que la mutación remota está completada.

En cuanto al contenido de la interfaz de usuario generado, configure la renderización del artefact como se describe en [Conversaciones y proyectos](conversations.md). El código generado no constituye una extensión confiable del Controller.

## Plantillas prácticas para agentes

- **Investigador de solo lectura**: examina los registros y las fuentes de información, compara las pruebas, informa sobre las causas del problema, sin realizar ninguna modificación en los datos recopilados.
- **Agent de implementación**: Edita un repositorio, ejecuta pruebas específicas, informa sobre las diferencias y los errores no resueltos. Se requiere aprobación para realizar operaciones sensibles, si es necesario.
- **Monitoreo del Agent:** Inspecciona las máquinas especificadas y reporta el estado, los errores y el progreso medido. No reinicia las tareas a menos que se autorice explícitamente.
- **Agent de investigación**: Permite realizar búsquedas en la red, citar documentos originales, distinguir entre pruebas y inferencias, y utilizar herramientas automáticas únicamente cuando sea necesario.

Los plantillas son instrucciones, no configuraciones predefinidas. Es necesario configurar las permisos y capacidades reales de cada agente, de manera que se ajusten a su función específica.
