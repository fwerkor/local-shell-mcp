<!-- i18n-source-sha256: 8ec601aa8e9c57afef769d8346567626355ccf88e122e3296735b7af3639c562 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat

LSM WebUI Chat es un espacio de trabajo para agentes de IA, que se encuentra integrado en el Controller. Puede utilizar su propio punto final de modelo o una cuenta compatible con el sistema. El modelo tendrá acceso a sus propias herramientas y máquinas. No es necesario utilizar ningún cliente externo para esto. Los clientes externos pueden seguir conectándose al mismo Controller, independientemente.

## Cómo los piezas encajan entre sí

- **Controlador:** Es el servicio en Python que aloja la aplicación web, maneja las solicitudes, ejecuta las herramientas necesarias, programa las tareas a realizar y mantiene el estado persistente de los datos.
- **Canal**: Se refiere a una conexión de tipo API, o a una autorización de cuenta compatible con ese tipo de conexión. Incluye las credenciales propias del canal, el protocolo utilizado, la lista de modelos y las configuraciones necesarias para el funcionamiento del canal.
- **Modelo**: Un identificador que sirve para distinguir un modelo dentro de un canal. El mismo identificador en dos canales no implica necesariamente que se trate del mismo endpoint.
- **Agent**: Una configuración reutilizable que combina un modelo, instrucciones, herramientas, habilidades y permisos.
- **Conversación:** Mensajes guardados, configuraciones, historial de ejecución y asociación entre el modelo/Agente.
- **Proyecto**: Un grupo de conversaciones con valores predeterminados compartidos entre todos los participantes.
- **Worker:** Un objetivo de ejecución conectado hacia el exterior. No se trata de un proveedor de modelos ni de un servidor de chat independiente.
- **Sesión lógica**: Es una identidad de tareas en el lado del instrumento, distinta de la identificación de una conversación. Un chat puede utilizar esta identidad para rastrear objetivos, progresos y el trabajo relacionado con el instrumento.

La API de modelo recibe el contexto visible para el modelo y los resultados obtenidos por las herramientas utilizadas. El controlador ejecuta las herramientas autorizadas; el modelo, por su parte, no se conecta directamente a ningún trabajador ni obtiene la clave de la API del modelo. El navegador es quien presenta la conversación y controla al controlador.

## Elija un guía.

| Quiero… | Leer |
|---|---|
| Instale la aplicación, inicie sesión y ejecute una tarea inicial. | [Prueba rápida](../getting-started/web-workspace.md) |
| Conecte una API o cuenta de modelo. | [Canales y modelos](channels.md) |
| Cree agentes reutilizables y delega tareas. | [Agentes y habilidades](agents.md) |
| Gestione chats, archivos y proyectos. | [Conversaciones](conversations.md) |
| Entienda cómo se recupera la información histórica y cómo se gestionan los presupuestos. | [Memoria y contexto](context.md) |
| Restringir la ejecución y gestionar las herramientas de MCP | [Herramientas y permisos](permissions.md) |
| Ejecutar tareas y horarios de larga duración. | [Objetivos y automatización](automation.md) |
| Buscar en la web y leer documentos. | [Búsqueda en red](../guides/webui-network-search.md) |
| Operar, realizar copias de seguridad y depurar una implementación. | [Administración y solución de problemas](administration.md) |

## Principios básicos.

Comenzar con una solicitud de tipo “solo lectura” en una máquina conocida. Verificar los resultados del instrumento antes de permitir cualquier modificación. Un modelo puede ser incorrecto, incluso cuando el instrumento funciona correctamente. Las credenciales del modelo, el almacenamiento de chat, el acceso a la máquina y la aprobación del instrumento son aspectos separados; cambiar uno no implica automáticamente que se conceda el acceso al otro. En particular, un punto final de chat público debe estar protegido como una plataforma de ejecución remota.

Para la ruta de conexión del cliente externo MCP, véase [conectividad de clientes](../clients/connectivity.md). Para los argumentos del instrumento, véase [referencia de herramientas](../reference/tools.md).
