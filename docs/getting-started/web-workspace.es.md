<!-- i18n-source-sha256: 01cf883cb71925e93fabc21d32315ef8c869ee2ea548e54a0347e2f6b730a327 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Inicio rápido de chat en WebUI

El espacio de trabajo web unificado LSM integra chat con inteligencia artificial, proyectos, agentes y las páginas operativas del controlador. Está gestionado por el controlador Python, que utiliza su sistema de autenticación y la base de datos SQLite. No es necesario tener un servidor de chat separado. Los clientes externos como [ChatGPT](chatgpt-connector.md) y [Gemini](gemini-spark.md) siguen siendo compatibles.

## 1. Iniciar el Controller

Siga las instrucciones de [inicio rápido de instalación](quickstart.md) para elegir el entorno de ejecución que prefiera. Asegúrese de que la interfaz web esté habilitada y de que se utilice almacenamiento persistente. Estos son los valores por defecto normales:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

Después de exportar el entorno de servicio, inicie el controlador.

```sh
local-shell-mcp --mode mcp
```

Para la distribución en forma de fila única, utilice el ejecutable descargado. El Controller instalado sirve como interfaz para el frontend compilado; el conjunto de herramientas de desarrollo JavaScript solo es necesario para las construcciones a partir del código fuente. Consulte las instrucciones de construcción de WebUI en [WebUI build instructions](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## 2. Abrir el espacio de trabajo en el navegador

Abra la página `http://127.0.0.1:8765/ui` desde el host del Controller, o desde la URL HTTPS configurada, que termina en `/ui`. Inicie sesión utilizando la autenticación LSM configurada para esa implementación. Utilice el acceso HTTPS autenticado para el acceso remoto. Las páginas de chat y control comparten la misma origen.

## 3. Añadir un canal de modelo

Abra el selector de modelos y la función de gestión de canales. Agregue un canal API o conecte una cuenta compatible. Para obtener un endpoint típico compatible con OpenAI, ingrese el nombre del canal, seleccione “Chat Completions”, ingrese la URL base de la API y las credenciales necesarias. También puede seleccionar un modelo manualmente. Guarde la configuración y elija un modelo adecuado.

Para un servicio de inferencia local, se debe utilizar una dirección a la que se pueda acceder desde el Controlador, y no simplemente desde el navegador. Por ejemplo, `http://127.0.0.1:8080/v1` es una dirección adecuada si el servicio de inferencia escucha en esa dirección dentro del espacio de nombres de red del Controlador. Para más información sobre los protocolos, la autorización de cuentas, el descubrimiento de modelos y los límites de contexto, consulte [Channels and models](../chat/channels.md).

## 4. Ejecutar una primera tarea

Inicie una conversación y haga una pregunta sencilla para verificar la conectividad del modelo. Luego, intente utilizar una herramienta de solo lectura.

```text
Indique los archivos que se encuentran en la raíz del espacio de trabajo del controlador.
Díganme qué máquina inspeccionó y resuma los resultados obtenidos.
No modifique los archivos ni ejecute ningún tipo de operación de escritura en ellos.
```

Verifique el resultado real del instrumento utilizado. Si falta algún instrumento, revise los ajustes relacionados con los instrumentos en el chat, la configuración del agente y las permisos de la máquina. Utilice un agente guardado para tareas recurrentes, y configure explícitamente su acceso. Consulte [Instrumentos y permisos](../chat/permissions.md).

![Chat en la interfaz web con una conversación de demostración](../assets/chat/chat-workspace.png)

Las capturas de pantalla que se presentan en esta guía y en las páginas siguientes fueron obtenidas en un Controller aislado, utilizando un modelo de demostración. Estas capturas de pantalla no contienen credenciales de producción ni conversaciones reales. Las etiquetas del interfaz de usuario en inglés pueden diferir de las etiquetas en el idioma seleccionado.

## 5. Explorar el espacio de trabajo

| Área | ¿Para qué se utiliza? |
|---|---|
| Chats y proyectos | Iniciar y buscar chats, organizar proyectos, etiquetas y marcadores de mensajes |
| Agents | Modelos, instrucciones y configuraciones de herramientas reutilizables |
| Memoria y habilidades | Gestionar conocimientos e instrucciones reutilizables |
| Chats programados | Ejecute al Agente guardado con un prompt recurrente. |
| Archivos y terminales | Se debe inspeccionar o operar en los entornos de Controlador y Trabajador. |
| Escritorio | Inspeccionar y controlar sesiones GUI remotas compatibles |
| Sesiones, trabajos y auditoría | Inspeccionar tareas duraderas, el progreso de la ejecución y las actividades del software utilizado. |
| Máquinas y componentes externos relacionados con el MCP | Gestionar trabajadores y servidores MCP anidados. |

El conjunto exacto de controles depende de la implementación, la cuenta utilizada y las capacidades habilitadas. Cerrar el navegador no cancela automáticamente la generación de datos en el lado del servidor; utilice el control “Stop” cuando sea necesario interrumpir el trabajo.

## Pasos siguientes

Lea la [Guía de Chat WebUI](../chat/index.md) para conocer el flujo de trabajo completo. Para información sobre configuraciones de producción, respaldo y recuperación de errores, consulte [Administración y solución de problemas](../chat/administration.md).
