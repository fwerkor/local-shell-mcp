<!-- i18n-source-sha256: 214687d6067b7dc2dd2b6eec1a207aa50be3ab9550d081f8a60e3013684c0250 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Memoria, contexto y uso de tokens.

## Tres tipos diferentes de estados

| Estado | Propósito |
|---|---|
| Historial de conversaciones | Los mensajes originales y las actividades relacionadas con las herramientas, están guardados por el controlador. |
| Ventana de contexto | El subconjunto de instrucciones, esquemas de herramientas, historiales, resúmenes y otros datos que se envían en una solicitud específica del modelo. |
| Memoria persistente | Datos y preferencias que pueden ser reutilizados en diferentes conversaciones, dentro del ámbito de memoria correspondiente. |

Una conversación que se ha guardado durante mucho tiempo puede superar el límite de espacio del modelo, sin que se pierda toda su historia. La memoria no significa que toda la historia de las solicitudes del usuario sea enviada a cada modelo.

## Gestionar la memoria

![Barra lateral de gestión de memoria con una entrada de ejemplo](../assets/chat/memory-management.png)

La memoria está habilitada por defecto, a menos que el usuario la deshabilite mediante sus configuraciones, la opción de chat o las restricciones relacionadas con la capacidad de implementación/agentes. Utilice la página de gestión de memoria para inspeccionar y editar los datos almacenados. Pídale al agente que recuerde hechos útiles, convenciones de proyecto o preferencias, y verifique el resultado en la interfaz de memoria.

Al editar una entrada de memoria, utilice una clave que contenga solo letras minúsculas y guiones bajos (por ejemplo, `repository_conventions`). El límite de longitud predeterminado es de 10,000 caracteres; una instalación puede configurar sus propios límites para el almacenamiento de memoria. Si una entrada es rechazada, analice el error en lugar de dividir las claves en varias partes.

La memoria puede utilizar un conjunto compartido para todos los agentes, o bien un ámbito específico para cada agente, dependiendo de la configuración del agente en cuestión. No se deben almacenar claves de API, contraseñas ni datos confidenciales en la memoria. Desactivar la memoria evita que se utilice en el ámbito correspondiente; esto no significa que se eliminen los datos almacenados o que se eliminen las menciones en el historial de conversaciones.

Cuando se expone al escenario de análisis, el modelo utiliza `set_memory` para crear o actualizar una entrada; un valor vacío elimina esa entrada. `find_memory` recupera las entradas mediante consultas o claves exactas. Una consulta vacía lista todas las memorias guardadas. La opción `include_conversations` permite buscar texto de otras conversaciones también. La paginación se realiza utilizando `page` (por defecto 1) y `limit` (por defecto 10; máximo 50). Este proceso de recuperación de historiales busca en el texto de las conversaciones, en lugar de en los registros de invocación de herramientas. La recuperación se realiza según la relevancia de los datos, por lo que es necesario utilizar nombres o términos precisos y refinar la consulta si es necesario.

La inyección automática de memoria y habilidades se mantiene estable durante las diferentes rondas de una conversación, con el objetivo de preservar los prefijos de prompts que pueden ser reutilizados en futuras conversaciones. La edición de la memoria almacenada no modifica retroactivamente los datos ya inyectados. El acceso explícito a la memoria permite recuperar los datos almacenados actualmente; se puede iniciar una nueva conversación si es necesario utilizar contexto recién inyectado.

## Capacidad de contexto

Se establece el límite de contexto real de cada modelo en su canal correspondiente. El Controller estima la cantidad de información visible para el modelo y reserva espacio para la salida. La implementación del presupuesto actual se basa en un ratio de compactación del 85% y un ratio de reserva del 5%. Estos valores pueden ser aproximados, especialmente cuando se trata de un tokenizer desconocido, una solicitud multimodal o un esquema específico del proveedor.

La composición del contexto puede incluir instrucciones del sistema, configuraciones de los agentes, definiciones de herramientas, archivos adjuntos, mensajes previos y resultados obtenidos por las herramientas. Un proveedor puede utilizar un tokenizer diferente o contar con tokens internos adicionales. Considere la visualización como una guía operativa, no como una garantía del proveedor.

## Compaction automática

Cuando el presupuesto del contexto requiere una reducción de tamaño, el controlador crea o actualiza un resumen del contexto anterior, manteniendo así la información reciente para futuras solicitudes del modelo. El resumen intenta conservar los objetivos, las restricciones, las decisiones tomadas, el progreso, los identificadores relevantes, los resultados obtenidos por los herramientas utilizadas y las próximas acciones a llevar a cabo. La información original se mantiene disponible para su inspección; el resumen, en cambio, es una aproximación generada por el modelo, y no una reproducción perfecta de la información original.

La compresión se realiza antes de la siguiente solicitud, lo que implica que el contexto se reduce en ese proceso. Si la operación de resumen falla, el motor intentará nuevamente, de acuerdo con su mecanismo de manejo de errores. No se debe continuar con el proceso utilizando una entrada que ya está demasiado comprimida. Es necesario revisar el estado de la compresión y los errores detallados si no se puede continuar con el proceso. Las mensajes recientes y las relaciones entre las herramientas utilizadas deben mantenerse coherentes. Los resultados obtenidos con las herramientas antiguas no deben ser reescritos continuamente, solo para reducir el tamaño del contexto.

Un único resultado enorme o herramienta puede, aún así, superar el presupuesto establecido. Se puede solicitar un resultado limitado en términos de cantidad, rangos de archivos o una versión resumida del resultado. Los resultados más grandes pueden almacenarse en archivos, y las partes específicas de dichos resultados pueden recuperarse, en lugar de tener que insertarse repetidamente en el contexto del modelo.

## Uso acumulado y número de hits en la memoria caché

La pantalla que muestra el uso de la sesión y la ventana de contexto responden a preguntas diferentes. El uso de entradas/salidas se acumula a lo largo de todas las solicitudes en la conversación, incluyendo el contexto repetido. Las métricas de caché describen el almacenamiento en caché de los prompts, cuando este está disponible. La ocupación del contexto mide el tiempo que utiliza el modelo activo, y no se suma con cada solicitud anterior.

Por ejemplo, una solicitud que contiene 20,000 tokens de entrada, seguida por otra solicitud que contiene 25,000 tokens de entrada, consume un total de 45,000 tokens de entrada. Pero la segunda solicitud utiliza aproximadamente 25,000 tokens de su capacidad actual de procesamiento. Los tokens almacenados en la memoria no son gratuitos, a menos que el proveedor esté dispuesto a ofrecerlo. Un límite más alto para el contexto del modelo cambia la capacidad de procesamiento, pero no afecta el uso de los tokens ya utilizados.

La compresión puede reducir la ocupación actual del modelo, pero al mismo tiempo aumenta el consumo de recursos del modelo. El cambio de modelos modifica los límites aplicables en el contexto; no se elimina el consumo previo. Si un proveedor omite información sobre el uso exacto o los metadatos de la caché, las estimaciones y métricas pueden ser incompletas. Para fines de conciliación financiera, se deben utilizar los datos de facturación y precios del proveedor, no solo la información mostrada en LSM.

## Reducir costos y preservar el contexto útil.

Mantenga las instrucciones del agente estables. Evite generar resultados de herramientas que sean demasiado grandes. Utilice métodos de recuperación específicos para obtener resultados precisos. Inicie una conversación separada para trabajos no relacionados con el objetivo principal. Cuando sea necesario realizar una transferencia de trabajo, guarde un punto de control conciso, que incluya las rutas exactas, los identificadores de los datos, los resultados obtenidos y las preguntas pendientes. Verifique los datos importantes en comparación con la fuente original o con los resultados obtenidos por la herramienta; no se deben confiar únicamente en un resumen generado automáticamente.
