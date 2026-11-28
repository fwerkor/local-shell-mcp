<!-- i18n-source-sha256: af41013e98ff8fbebf496514fd0034d1c97f3177d7e73f77f7c0c21f6022047b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Conversaciones y proyectos.

## Crear y continuar una conversación.

Abra una nueva conversación, elija un canal/modelo o Agente y escriba un mensaje. El chat se ejecuta en el Controller, y las actualizaciones se transmiten al navegador. Recargar la página o cerrar una pestaña no equivale a cancelar la ejecución del proceso. Utilice el control “stop” para interrumpir la ejecución, y verifique el estado resultante antes de iniciar otra operación.

Un chat guardado conserva su asociación con el modelo/Agent correspondiente. Puede cambiarlo si se desea utilizar un modelo diferente. Una conversación no es una Sesión Lógica: en ella se almacenan tanto los mensajes del usuario como los del modelo. En cambio, una Sesión Lógica contiene información relacionada con las tareas a realizar, el progreso y el plan de trabajo. Es importante mantener los identificadores relevantes cuando se transfiere una tarea larga.

## Organizar y encontrar trabajo.

Se pueden utilizar proyectos para agrupar conversaciones relacionadas y establecer los permisos de uso compartidos en las máquinas. Un proyecto puede contener varios chats separados. Se deben mover o crear chats dentro del proyecto correspondiente, en lugar de asumir que las conversaciones separadas comparten todo su contexto. El proyecto activo puede informar al agente sobre la organización de las conversaciones.

Las etiquetas clasifican las conversaciones; los marcadores de mensajes indican los mensajes individuales y permiten navegar de nuevo hacia resultados útiles. Estos elementos están separados del hecho de anclar una conversación en la barra lateral. Utilice los títulos de chat, la búsqueda, los archivos y los indicadores de mensajes no leídos para mantener una barra lateral organizada.

El archivado consiste en mover una conversación fuera de la lista normal, sin eliminar su historial guardado. Se puede restaurar esa conversación a través de la interfaz de archivado, cuando sea necesario. Eliminar una conversación es un acto destructivo; no utilice la eliminación como alternativa al archivado. La implementación actual utiliza el formato SQLite para almacenar el estado de las conversaciones. No asuma que el antiguo formato de archivado comprimido de Hosted Chat sigue siendo válido.

## Operaciones de mensajes y ejecución de tareas

Los controles disponibles para los mensajes dependen del mensaje en cuestión y del estado en el que se encuentra su ejecución actual. Es posible editar o intentar nuevamente una acción en un determinado turno, cuando sea necesario. También se puede eliminar un turno de usuario/asistente si ya no es necesario. La eliminación modifica el historial de conversaciones guardadas y puede afectar el contexto posterior. No es posible deshacer comandos de shell, escrituras remotas, pushs en Git u otros efectos secundarios externos.

Al intentar nuevamente una operación que falló, lea los errores detallados y verifique primero las llamadas a herramientas que ya se han realizado. Si una operación de escritura pudo haber tenido éxito antes de la desconexión, verifique el estado externo antes de repetirla. Si hay otro mensaje en espera o si otra operación ya está en ejecución, utilice los controles y el estado que se muestran, en lugar de asumir que múltiples operaciones se ejecutan simultáneamente en el mismo chat. El panel de mensajes en espera le permite verificar las operaciones pendientes. El control de dirección intenta proporcionar orientación dentro de límites seguros, una vez que las herramientas actualmente en ejecución terminen su trabajo. Ninguna de estas operaciones puede anular los efectos de las herramientas ya completadas.

## Archivos adjuntos, vistas preliminares y datos relacionados

Se puede utilizar el control de archivos adjuntos para cargar archivos o imágenes compatibles con el sistema. La implementación de la función de carga limita los tamaños de los archivos adjuntos a 32 MiB. Además, los límites impuestos por el servidor proxy pueden reducir aún más este límite efectivo. Los archivos cargados se almacenan en el Controller y pueden ser referenciados mediante el modelo correspondiente. La interpretación de las imágenes requiere que exista un modelo y un proveedor que puedan manejar los datos relacionados con las imágenes. La carga de archivos no implica la autorización para acceder a archivos locales o remotos que no estén relacionados con el proceso en cuestión.

Al solicitar un archivo generado, especifique la ruta de acceso, el formato y el contenido deseados. Verifique que el archivo exista antes de compartirlo. Descargue o vea una vista previa de los archivos y datos disponibles en el chat. Un archivo generado en un Worker puede necesitar ser transferido al Controller o a un enlace de archivo adecuado. Consulte [Enlaces de archivos](../guides/file-links.md).

La representación de artefactos puede mostrar React, HTML, SVG, Markdown y Mermaid en un panel lateral, en lugar de solo como código. En la configuración de los artefactos del agente, el modo “Normal” utiliza las instrucciones estándar; el modo “shadcn/ui” añade guías relacionadas con las bibliotecas de componentes; mientras que el modo “Custom” permite la representación de los artefactos sin las instrucciones integradas. Considere el código generado o el contenido representado como algo no confiable; reviselo antes de utilizarlo fuera del área de previsualización. Las previsualizaciones y descargas basadas en archivos son distintas de los artefactos de interfaz de usuario generados.

No cargue credenciales, claves privadas ni documentos que no tenga autorización para enviar al proveedor de modelos seleccionado. La eliminación de archivos adjuntos y de los mensajes de chat es algo separado de la eliminación de los archivos originales en la máquina.

## Preferencias

Las preferencias del usuario, como los botones de configuración y las combinaciones de teclas, se gestionan a través de la interfaz web. Estas preferencias se almacenan en el servidor donde están implementadas. Para configurar el comportamiento del teclado, se puede acceder a los Ajustes. Es importante distinguir entre enviar un mensaje y insertar una línea nueva en el texto. Las configuraciones relacionadas con los botones de configuración deben realizarse por separado, en comparación con las permisos del agente. Consulte [Herramientas y permisos](permissions.md) y [Memoria y contexto](context.md).

### Nombres automáticos de conversaciones

En Ajustes → Chat → Conversaciones, elija entre no asignar nombres automáticamente, nombrar los chats nuevos una vez o cambiar el nombre tras cada respuesta completada. De forma predeterminada, se nombra cada chat nuevo una vez con su propio modelo. También puede seleccionar otro modelo de un canal configurado. El nombre se genera solo al terminar la respuesta principal; las respuestas fallidas o canceladas no lo activan. El título describe brevemente la tarea en el idioma del usuario. La solicitud de nombre es independiente del contexto y no añade mensajes al chat.
