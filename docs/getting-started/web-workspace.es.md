<!-- i18n-source-sha256: e75cf6e4ffc3fe904983cd63b99b43c2877c4bdd99174b2d4a96393eff5d9e3f -->
# Espacio de trabajo web unificado

El **espacio de trabajo web unificado de LSM** es la forma recomendada de utilizar local-shell-mcp en el día a día. Combina el chat de IA, el historial del proyecto y el plano de control LSM en una interfaz responsiva, basada en una interfaz LibreChat modificada y suministrada. Aún puede conectar clientes MCP externos como [ChatGPT](chatgpt-connector.md) o [Gemini](gemini-spark.md).

El espacio de trabajo es **autohospedado y su instalación es opcional**: es un servicio web independiente, que no forma parte de la imagen mínima del controlador, del ejecutable independiente ni del paquete de trabajador remoto. Las implementaciones de solo controlador conservan la interfaz de usuario del navegador original y OpenTUI.

## ¿Qué hay en el espacio de trabajo?

| Área | que puedes hacer |
|---|---|
| Chat y proyectos | Elija un modelo configurado, cree conversaciones, organice proyectos, busque chats anteriores y archive conversaciones. La historia permanece en el servidor. |
| Descripción general del controlador | Ver estado, actividad reciente y máquinas conectadas. |
| Archivos | Explore y administre archivos locales o remotos. |
| Terminales | Trabajar con terminales persistentes en el Controlador o Trabajadores. |
| Escritorio | Inspeccionar y controlar sesiones GUI remotas. |
| Sesiones | Inspeccione tareas LSM duraderas y su ciclo de vida. |
| Mandos a distancia | Conecte y administre trabajadores salientes. |
| Auditoría | Inspeccionar la actividad de la herramienta originada en el modelo. |
| MCP anidado | Registre, edite, habilite, deshabilite, actualice y elimine servidores MCP externos detrás de LSM. |

Las rutas del controlador son `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` y `/control/audit`. El chat se abre en `/c/new`. El administrador de LSM MCP controla **el registro de MCP anidado de LSM**; no crea un segundo registro en LibreChat.

## Implementar la pila de chat opcional

1. [Install and start an LSM Controller](quickstart.md) con OAuth, un espacio de trabajo adecuadamente aislado y almacenamiento de estado persistente `file` o `redis`. Instale Docker Compose y clone el repositorio en el host que ejecuta la pila web.
2. Proporcione **dos orígenes HTTPS en el mismo sitio**, como `https://lsm.example.org` para el controlador y `https://chat.example.org` para el espacio de trabajo. El servicio de chat no está expuesto directamente en una red que no sea de confianza.
3. Genere un secreto de puente con `openssl rand -hex 32`. Configure estas variables de entorno en el **servicio del controlador**, usando ese secreto, luego reinícielo:

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. En la caja del repositorio, configure la pila web opcional. Utilice un archivo de entorno privado o exporte los valores que se muestran a continuación; Genere secretos fuertes únicos y no los cometa:

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Represente la configuración privada, luego cree e inicie la pila de chat implementada por separado:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

Cuando se utiliza la implementación raíz de Docker Compose, las variables del controlador anteriores pertenecen a la raíz `.env` y se reenvían al contenedor. Los valores del servicio de chat se pueden proporcionar mediante exportaciones de shell o un archivo de entorno privado. Se debe poder acceder al contenedor del controlador desde el contenedor de chat en `http://local-shell-mcp:8765` en la red Docker denominada. Puerto de proxy inverso `127.0.0.1:3080` al origen HTTPS del chat, conserve el host externo y siga [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) en el repositorio. La pila web ejecuta Node.js, MongoDB, Meilisearch y SearXNG; **no** están incluidos en Trabajadores. Esta implementación separada no se inicia mediante un `docker compose up -d` simple en la raíz del repositorio.

## Inicia sesión y usa el chat

1. Abra `https://lsm.example.org/ui`, autentíquese utilizando el inicio de sesión del **Controlador LSM** y siga la transferencia única al espacio de trabajo web. No crea una segunda cuenta de usuario de LibreChat.
2. Configurar un proveedor de modelo. La pila web opcional expone las credenciales de OpenAI, Anthropic y Google como `user_provided` de forma predeterminada: ingrese su propia clave de proveedor en la configuración del punto final del chat, o configure `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` o `GOOGLE_KEY` en el entorno de redacción del chat antes de comenzar. Elija un modelo compatible en el chat. **LSM no incluye modelos ni créditos API.** La conexión MCP externa de Gemini Spark es independiente de la configuración de un modelo Gemini aquí.
3. Crea una conversación. Las herramientas de búsqueda web y LSM están habilitadas de forma predeterminada, sujetas a los permisos del Controlador. Utilice los controles por conversación **Web**, **LSM**, **MCP externo** y **Memoria** según sea necesario.
4. Comience con una solicitud de solo lectura: "Verifique el estado del controlador y enumere la raíz del espacio de trabajo. No modifique los archivos".
5. Navegue a **Archivos**, **Terminales**, **Escritorio**, **Sesiones**, **Remotos** o **Auditoría** para inspección y control directos.

Las cargas de chat (hasta 32 MiB) se almacenan en el espacio de trabajo del Controlador y sus rutas absolutas se proporcionan al modelo. Las cargas del navegador no otorgan permisos de archivos adicionales. Las llamadas a herramientas orientadas al modelo pasan por la autorización LSM, la auditoría y el enrutador del trabajador remoto.

## MCP externo, seguridad y datos

Utilice la barra lateral de MCP del espacio de trabajo para administrar servidores MCP externos anidados. Esto admite servidores stdio locales y servidores HTTP, incluidas variables de entorno privadas independientes y encabezados de solicitud. Los secretos no se devuelven al navegador. La opción de chat **MCP externo** permite buscar, inspeccionar e invocar herramientas anidadas; no otorga el modelo `mcp_manage` cuando las herramientas LSM nativas están deshabilitadas. La gestión de la interfaz de usuario está protegida por la autorización normal del Controlador.

Los mensajes de chat, proyectos y archivos se almacenan en el lado del servidor en MongoDB de la pila web; La búsqueda utiliza Meilisearch. El Controlador posee por separado los permisos de herramientas, las identidades de los trabajadores, el estado de la sesión y la auditoría. Haga una copia de seguridad de ambos almacenes de datos si necesita conservar todo el historial. El backend del chat es de un solo usuario con el inicio de sesión de LSM; no exponga su API interna ni sus bases de datos al público.

La interfaz de usuario es una aplicación de nivel superior, **no un iframe**. Si el servicio de chat opcional no está configurado, `/ui` continúa brindando la WebUI de LSM original. OpenTUI nativo y clientes externos siguen siendo compatibles.

## Solución de problemas

- **La redirección permanece en la interfaz de usuario original:** marque `LOCAL_SHELL_MCP_LIBRECHAT_URL`, un backend de estado de controlador persistente y el proxy inverso HTTPS de la pila web.
- **El inicio de sesión o la transferencia fallan:** verifique exactamente el mismo secreto de puente de 32 bytes o más en ambos lados, que coincida con los orígenes del mismo sitio, HTTPS y relojes del servidor.
- **El chat se carga pero no puede responder:** configure un punto final de modelo real o una credencial de API y verifique los registros del contenedor de chat.
- **Faltan herramientas MCP:** verificar los alcances del controlador y los cambios por conversación; el registro del servidor anidado está separado de la base de datos de LibreChat MCP.
- **Los archivos o sesiones aparecen vacíos:** verifique que el chat llegue al controlador y al espacio de trabajo correctos, e inspeccione sus registros de autenticación de API.

Para obtener detalles de implementación y actualizaciones, consulte [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) y [human interface guide](../guides/human-interface.md).
