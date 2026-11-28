<!-- i18n-source-sha256: a40a962d4db93cc0aac03601ffd13b21ab3a504c9bff930ab4b8173c4cfa4537 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Canales y modelos

## Configurar un canal

Abra el selector de modelos en Chat y ingrese a la sección de gestión de canales. Seleccione… **Añadir canal**Elija el tipo de conexión, introduzca la información necesaria y guarde los cambios. Para crear un nuevo chat, seleccione un modelo correspondiente al canal en cuestión. Si desea utilizar un agente personalizado, seleccione el canal y el modelo en la configuración del agente.

Los canales están controlados por el Controller, no son configuraciones de chat personales. En implementaciones autenticadas, la gestión de canales requiere el ámbito de acceso `admin:config`. Un administrador puede configurar canales compartidos sin necesidad de distribuir claves de API a los usuarios del chat.

![Añadir un canal de modelo en el diálogo de configuración del canal](../assets/chat/channel-settings.png)

Un canal normal de API tiene un nombre, protocolo del proveedor, URL base, credenciales y identificadores de modelos. Utilice una clave de API emitida para el punto final seleccionado, no la contraseña de su cuenta de LSM. LSM realiza solicitudes desde el Controller; un URL que funciona en tu ordenador puede no funcionar desde el Controller.

| Protocolo | Ejemplo de URL base de API | Uso |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | Puertas de entrada compatibles con OpenAI y servidores locales de inferencia |
| OpenAI Responses | `https://api.openai.com/v1` | Un puerto que exponen la API de Respuestas |
| Nativo antrópico | `https://api.anthropic.com/v1` | APIs compatibles con mensajes de Anthropic |
| Nativo de Google Géminis | `https://generativelanguage.googleapis.com/v1beta` | APIs compatibles con Gemini generateContent |

Utilice la URL base requerida por el proveedor, en lugar de copiar una URL completa para realizar solicitudes, como una URL que termina en `/chat/completions`. Un gateway que afirma ser compatible con OpenAI puede soportar las funcionalidades de Chat Completions, pero no las de Respuestas, llamadas a herramientas, uso de streaming, entradas multimodales o opciones de razonamiento. Elija el protocolo que realmente soporta ese gateway. Los ejemplos de URL son solo ejemplos, y no representan una promesa de acceso gratuito o disponibilidad.

## Punto final locales y personalizados

Para un servidor compatible con OpenAI que escuche en el propio Controller, la dirección URL base podría ser `http://127.0.0.1:8080/v1`. Cuando se ejecuta en Docker, “loopback” se refiere a ese contenedor, no al host físico. Es necesario utilizar una dirección de red accesible desde el espacio de nombres de red del Controller. La registración de un trabajador remoto por sí sola no garantiza que su API de inferencia esté disponible.

El validador de URL del modelo requiere que se utilice el protocolo HTTPS, excepto en el caso de HTTP en hosts locales como `localhost`, `127.0.0.1` y `::1`. Un punto final HTTP ubicado en una dirección LAN o en el nombre de un servicio Docker debe estar expuesto a través de un gateway HTTPS. La opción de activar o desactivar el punto final privado de Chat no es aplicable en este caso. Los URL básicos no deben incluir credenciales incrustadas, fragmentos o cadenas de consulta.

Utilice TLS para los puntos finales remotos. Restrinja el acceso a las puertas privadas de confianza y verifique los identificadores del modelo con el servidor de inferencia. Nunca guarde las claves de API en prompts, capturas de pantalla, cadenas de consulta o configuraciones publicadas. Deje en blanco la clave de API al editar un canal existente, para preservar la clave guardada; utilice una conexión sin clave solo cuando el servicio lo permita.

## Valores predeterminados configurados por el entorno

El perfil integrado de OpenAI puede configurarse antes del lanzamiento, utilizando `LOCAL_SHELL_MCP_MODEL_BASE_URL` (o `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL` y `LOCAL_SHELL_MCP_MODEL_API_KEY` (o `OPENAI_API_KEY`). Los perfiles integrados de Anthropic y Google pueden leer `ANTHROPIC_API_KEY` y `GOOGLE_KEY` / `GOOGLE_API_KEY`, respectivamente. Los perfiles integrados guardados tienen prioridad sobre los valores predeterminados del entorno; utilice canales nombrados para múltiples puntos finales independientes. Los valores predeterminados configurados por el entorno no son una alternativa para proteger las claves del servicio.

## Autorización de la cuenta de ChatGPT

El canal “Account/Codex” utiliza un flujo de autorización compatible con ChatGPT, en lugar de una clave API normal. Inicie la autorización desde la gestión del canal y inicie sesión en la página oficial de autorización. En una implementación local, el llamado backend puede completarse automáticamente. Si el navegador no puede acceder al escucha de loopback, copie toda la URL del llamado backend desde la barra de direcciones y pégalo en el diálogo de autorización. Se espera que ocurra un error de conexión en la dirección de loopback en este flujo manual.

Trate la URL de devolución de llamada como una credencial: nunca la envíe en una conversación ni la publique. El Controller guarda la autorización en el servidor y renueva las credenciales cuando es posible. Vuelva a autorizar la cuenta si caduca o se revoca el acceso. Los modelos disponibles, los límites del plan y el uso permitido los determina el servicio de cuenta de origen; LSM no proporciona cuota adicional de suscripción.

## Modelo de descubrimiento y limitaciones del contexto

Habilite el descubrimiento automático para solicitar información sobre los modelos del proveedor. El controlador actualiza esta información periódicamente (actualmente cada diez minutos); también es posible realizar una actualización manual. En caso de fallo en el proceso de descubrimiento, los datos del modelo guardados anteriormente se mantienen. Si el proveedor no cuenta con un endpoint compatible para listar los modelos, desactive el proceso de descubrimiento y introduzca los identificadores de los modelos manualmente, uno por línea.

El descubrimiento reconoce metadatos explícitos de la ventana de contexto, incluidos `limit.context` anidado de OpenCode Go/Zen, `context_length` de OpenRouter, `max_model_len` de vLLM e `inputTokenLimit` de Gemini. Si solo se informa de la longitud máxima de entrada, se utiliza como alternativa; los límites de salida y los nombres de los modelos no determinan la capacidad de contexto. Sin ninguno de estos datos, la ventana sigue siendo desconocida.

Especificar la ventana de contexto para cada modelo, cuando esto sea posible. Una valor explícita por modelo puede reemplazar los metadatos descubiertos o completar los valores que faltan. El editor acepta entre 1 y 2,000,000 tokens; se trata de un rango de configuración, no una garantía de que el proveedor soporte esa capacidad. Utilice el límite efectivo adecuado para su implementación, teniendo en cuenta la configuración del lado del servidor y los límites propios del modelo.

## Muestreo, razonamiento y uso

Los valores predeterminados del canal y del modelo controlan los parámetros de solicitud que es compatible con el proveedor seleccionado. El compilador de chat puede indicar los pasos necesarios para realizar la solicitud, si los hay. Los diferentes protocolos implementan el muestreo y el procesamiento de datos de manera diferente; una opción puede no ser compatible con un determinado modelo. Comience por los valores predeterminados del proveedor, y luego cambie uno de los parámetros a la vez.

LSM puede solicitar el uso exacto de tokens de transmisión. Pero puede recurrir a otra opción cuando el proveedor rechaza explícitamente esa opción. Un punto final que no devuelve información sobre el uso de los recursos no puede proporcionar datos precisos para la facturación o las estadísticas de caché. Para más detalles, véase [Memoria y contexto](context.md).

## Cambiar y eliminar canales.

Una conversación conserva su modelo/Agente y su historial correspondientes. Es necesario cambiar el modelo de forma deliberada cuando se modifican los puntos finales o cuando se debulle algún problema con un proveedor. El nombre de un canal en uso está restringido, para proteger las referencias a ese canal. La eliminación de un canal en uso requiere una confirmación adicional: el historial del canal permanece, pero los Agentes y los chats que hacen referencia a ese canal deben elegir un sustituto viable antes de continuar con la ejecución.

La configuración de los canales se realiza en el lado del servidor, y no es algo que se establece únicamente en el navegador. Las credenciales no se devuelven a través de las respuestas normales del catálogo de canales. Es necesario proteger la carpeta de estado del controlador y las copias de seguridad, ya que contienen datos que pueden ser utilizados como credenciales.

## Lista de comprobaciones para la conexión.

1. Confirme que el Controller puede acceder al host de la API, y que el protocolo TLS está configurado correctamente.
2. Verifique la ruta base, el protocolo, las credenciales y el ID exacto del modelo.
3. Actualice el catálogo de canales o ingrese manualmente un modelo conocido.
4. Envíe un mensaje de texto simple, luego pruebe a llamar a una herramienta pequeña.
5. Verifique los detalles de los errores, como el estado HTTP, los tiempos de espera o las opciones no compatibles. No intente repetidamente usar credenciales inválidas.

Para más información sobre cómo manejar los límites de velocidad, las interrupciones de transmisión y los errores de autorización, véase [Administración y solución de problemas](administration.md).
