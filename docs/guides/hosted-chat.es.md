<!-- i18n-source-sha256: 53d1b81800534bc6d5334883b7de74660c988088c66f492ddbd68aced8797379 -->
# Chat alojado (opcional)

Hosted Chat es un cliente de aplicaciones MCP y chat BYOK autohospedado integrado en la interfaz humana de LSM. **No** es un modo de sesión lógica: las conversaciones tienen identidades independientes y, opcionalmente, pueden adjuntar una sesión lógica LSM existente. ChatGPT y otros clientes externos continúan trabajando con las mismas sesiones y herramientas de LSM.

## Habilitar

El chat alojado está deshabilitado de forma predeterminada. Conjunto:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Reinicie el controlador y abra **Chat alojado** inmediatamente debajo del selector Web UI/TUI. La función también tiene una entrada en la barra superior móvil. El anfitrión del chat utiliza la identidad y los ámbitos de LSM OAuth existentes. El mismo controlador opera el servidor MCP utilizado por el bucle de herramientas del modelo; Los trabajadores no pueden iniciar la ejecución.

## Perfiles de modelo

Elija **Perfiles de modelo** para crear/editar un perfil con un nombre, URL base de API compatible con HTTPS OpenAI, ID de modelo y clave API opcional. Pueden coexistir múltiples perfiles y las conversaciones pueden cambiar de modelo.

Los perfiles, las conversaciones, el historial completo de mensajes y los resultados de las llamadas a herramientas se **guardan en el servidor** a través del backend de estado LSM configurado. Su alcance está vinculado al principal autenticado. La clave API está cifrada con AES-GCM y nunca se devuelve desde los puntos finales de lista de perfiles o detalles de perfil. No se almacena en el almacenamiento del navegador, no se envía al modelo como un mensaje ni se incluye en los registros de auditoría. El anfitrión del chat lo pasa solo a la API del modelo elegido.

La primera implementación respaldada por archivos crea `hosted-chat-encryption-key` en el directorio de estado con el modo 0600. **Haga una copia de seguridad de este archivo junto con los datos de estado. Sin él, las claves API guardadas no se pueden descifrar.** Si el controlador usa Redis, múltiples réplicas u otro backend sin estado de archivo, configure una clave URL-safe-base64 compartida y estable de 32 bytes:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

No gire esta configuración sin migrar los perfiles cifrados. No utilice el almacenamiento de estado en memoria cuando se requieran conversaciones duraderas.

De forma predeterminada, solo se aceptan puntos finales modelo HTTPS con nombres de host DNS; Se rechazan los puntos finales locales/privados y HTTP para reducir el riesgo de falsificación de solicitudes del lado del servidor. Los administradores que alojan deliberadamente una puerta de enlace modelo privada confiable pueden optar por:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

No habilite esto en un controlador multiusuario que no sea de confianza a menos que los usuarios estén autorizados a comunicarse con servicios internos.

## Conversaciones y aplicaciones MCP

Cree una conversación utilizando un perfil de modelo guardado. Cada turno enviado se convierte en una tarea en segundo plano propiedad del servidor; cerrar el navegador no cancela la tarea. El texto completo y las llamadas a herramientas se controlan de forma duradera entre los pasos del modelo/herramienta. Deténgase explícitamente para interrumpir. Al reiniciar el controlador, las ejecuciones interrumpidas se marcan como tales y pueden continuar en un nuevo turno, pero **las llamadas a herramientas con resultados desconocidos nunca se repiten automáticamente**.

Todo el historial de mensajes de la conversación se conserva en el almacenamiento. Solo se envía al modelo una ventana reciente limitada a la vez para controlar el tamaño del contexto. Las llamadas a herramientas se envían a través del punto final MCP autenticado de LSM, preservando todos los permisos ordinarios de las herramientas y el comportamiento de auditoría/verificación previa.

Archivar retira las conversaciones de la lista habitual y las guarda como `.json.zst` mediante el códec zstd ya usado por Audit. No aparecen en el índice de búsqueda normal. En **Archived conversations** se pueden localizar por título, consultar en modo de solo lectura, restaurar o borrar definitivamente. Primero se escribe la copia nueva para evitar pérdida de datos.

### Conversaciones largas y compactación del contexto

El historial completo de mensajes y herramientas permanece en el servidor. Cada perfil de modelo permite configurar la ventana de contexto: **32.768 tokens** por defecto, entre 8.192 y 1.000.000. Una estimación prudente basada en UTF-8 incluye las definiciones de herramientas; cerca del **80 %** se resume con el mismo modelo el historial de turnos completos anteriores. El resumen conserva objetivos, restricciones, decisiones, archivos, resultados y tareas pendientes, y se guarda separado del historial original. El modelo recibe el resumen y los mensajes recientes.

El presupuesto vuelve a comprobarse después de las herramientas. **Compact** activa la compactación manual si no hay un turno en ejecución. Los errores dejan intactos el resumen anterior y todos los mensajes. El cálculo de tokens es aproximado; los turnos actuales demasiado grandes se rechazan sin truncamiento silencioso.

Abra **Live Workspace** para representar el recurso de aplicaciones MCP `workspace_open` existente de LSM dentro de una vista incrustada. El host utiliza el puente `@modelcontextprotocol/ext-apps` para el ciclo de vida de la aplicación, la renovación de credenciales, las llamadas a herramientas y las acciones de persona a agente. No se implementa ningún segundo administrador de archivos, terminal, auditoría o interfaz de usuario de trabajo.

El `session_id` opcional adjunto permite que el chat alojado use y muestre una sesión lógica existente; no reclasifica la Sesión ni otorga la propiedad de la misma al Hosted Chat. Los identificadores de conversación de chat y los identificadores de sesión lógica están separados.

## Límites

- Las solicitudes de modelo utilizan finalizaciones de chat compatibles con OpenAI con llamada de herramientas; otros protocolos de proveedores requieren un adaptador.
- Las salvaguardias por turno limitan las iteraciones del modelo y las llamadas a herramientas. Las tareas más largas pueden continuar en un nuevo turno utilizando la historia duradera.
- La eliminación de la conversación de chat es explícita. No se realiza ningún desalojo automático del historial.
- El controlador debe ser accesible en red por su propio cliente MCP y el navegador debe estar autorizado para la API LSM Live Workspace.
