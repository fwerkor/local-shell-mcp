<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# Automatización de la GUI de escritorio

`local-shell-mcp` puede observar y controlar aplicaciones de escritorio nativas en Linux, Windows y macOS. La superficie pública se mantiene intencionadamente pequeña:

| Herramienta | Objetivo |
|---|---|
| `gui_list` | Enumere las ventanas de aplicaciones visibles e informe el backend/las capacidades nativas activas. |
| `gui_state` | Observe una ventana. Devuelve un `state_id` de corta duración, elementos de accesibilidad, geometría de ventana y, opcionalmente, una captura de pantalla MCP nativa. |
| `gui_action` | Ejecutar acciones semánticas o coordinar contra esa observación exacta. |

Las tres herramientas aceptan `machine` opcional, por lo que el mismo flujo de trabajo puede dirigirse a un trabajador de escritorio conectado.

## Observa y luego actúa.

Comience con `gui_list`, seleccione un `window_id` y luego llame a `gui_state`. Prefiera la accesibilidad devuelta `element_id` siempre que uno represente el control de destino:

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Utilice coordenadas `x`/`y` relativas a la ventana solo cuando la interfaz de usuario no tenga ningún elemento de accesibilidad útil, como un lienzo o un control dibujado personalizado. Los límites de elementos devueltos y las capturas de pantalla utilizan el mismo espacio de píxeles lógico relativo a la ventana, incluidos los escritorios HiDPI/Retina. Se rechazan las coordenadas sin procesar fuera de la ventana seleccionada.

Un `state_id` caduca después de 30 segundos y es de un solo uso. Las acciones coordinadas también verifican que la ventana objetivo no se haya movido ni cambiado de tamaño desde la observación. Si cualquiera de las comprobaciones falla, vuelva a llamar a `gui_state` en lugar de reutilizar coordenadas obsoletas.

Las acciones admitidas son `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus` y `wait`.

## Control humano en WebUI nativa

La UI web nativa tiene una página **Escritorio** para el control humano directo de los mismos backends de la GUI nativa. Elija una máquina y una ventana, luego interactúe con la imagen de la ventana en vivo haciendo clic, haciendo doble clic, haciendo clic derecho, arrastrando, rueda, atajos de teclado o el campo de texto para entrada IME/CJK.

Esta ruta está intencionalmente separada de la semántica del modelo `state_id`. Cada marco mostrado lleva la geometría de la ventana observada; cada solicitud de entrada humana valida que la ventana todavía tiene exactamente esa geometría antes de inyectar la entrada. Si la ventana se movió, cambió de tamaño o desapareció, la acción se rechaza y la WebUI actualiza la observación. Las coordenadas sin procesar permanecen limitadas a la ventana seleccionada.

Las acciones de teclado y texto enfocan explícitamente la ventana nativa seleccionada antes de la inyección. La WebUI utiliza un sondeo de captura de pantalla liviano en lugar de transmisión de video VNC/WebRTC, y el RPC `gui_human_action` solo remoto es una operación interna de controlador a trabajador en lugar de una herramienta MCP expuesta a modelos.

## Motores nativos

| Plataforma | Accesibilidad/control semántico | Captura y entrada sin procesar |
|---|---|---|
| ventanas | Automatización de la interfaz de usuario de Microsoft | Captura UIA/ventana más entrada nativa de teclado y mouse de Windows |
| macos | Accesibilidad (`AXUIElement`) | `screencapture` para la ventana seleccionada más entrada Quartz `CGEvent` |
| linux | AT-SPI | Entrada/captura nativa X11; Wayland utiliza captura de escritorio nativa y XDG Desktop Portal RemoteDesktop/ScreenCast para entrada sin formato |

Siempre que sea posible, se intentan primero las acciones semánticas. Por lo tanto, se puede activar un botón con una acción nativa de invocar/presionar sin adivinar una coordenada de píxel. Las coordenadas visuales siguen siendo la alternativa para contenido inaccesible o personalizado.

## Configuración de la plataforma

### ventanas

Ejecute LSM en la misma sesión de escritorio interactivo que las aplicaciones que debería controlar. La instalación básica `local-shell-mcp` permanece segura y no requiere el adaptador de automatización de la interfaz de usuario de Windows; instale el extra opcional `local-shell-mcp[gui]` cuando sea necesario el control local de la GUI de Windows.

### macos

Otorgue el proceso de host LSM:

- Permiso de **Accesibilidad** para entrada y control semántico.
- **Permiso de grabación de pantalla** para capturas de pantalla.

El paquete base no requiere PyObjC. Instale el extra opcional `local-shell-mcp[gui]` cuando sea necesario el control GUI local de macOS; Las máquinas que nunca usan herramientas GUI no necesitan estos marcos.

### linux

La sesión de escritorio debe exponer AT-SPI. Los sistemas Debian/Ubuntu normalmente proporcionan los enlaces de sistema necesarios con:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

El paquete base no requiere los adaptadores Python X11 o D-Bus. El extra opcional `local-shell-mcp[gui]` los instala para uso de GUI local. Los trabajadores remotos detectan la sesión activa de Linux antes de que se inicie cualquier dependencia de GUI: X11 solo necesita el adaptador X11, Wayland solo necesita el adaptador D-Bus y los trabajadores sin cabeza no instalan ninguno. En Wayland, el respaldo sin formato de puntero/teclado utiliza la API de escritorio remoto del portal de escritorio XDG, por lo que el escritorio puede mostrar un selector de sesión/permiso único. Se admiten implementaciones de portales KDE y GNOME. Las capturas de pantalla de Windows utilizan la ruta de captura de escritorio nativa disponible y recurren al portal de capturas de pantalla cuando es necesario.

Los trabajadores de LSM normalmente comienzan fuera del entorno de inicio de sesión gráfico. El backend de Linux recupera `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE` y variables relacionadas del entorno systemd del usuario cuando no se heredan directamente.

## Escritorios remotos

Las herramientas GUI se ejecutan en la máquina seleccionada, no en el controlador. El trabajador remoto debe pertenecer al usuario/sesión propietaria del escritorio de destino. Los adaptadores de GUI son vagos y están destinados a llamadas de GUI: el inicio normal del trabajador y el uso de shell/archivos/navegador no los instalan ni importan. En Linux, un trabajador sin cabeza devuelve una GUI no disponible antes de que se inicie cualquier pip de GUI; un trabajador gráfico solo verifica o instala el adaptador requerido por su sesión activa X11 o Wayland.

Las capturas de pantalla devueltas por un `gui_state` remoto se transfieren a través de la ruta de transferencia de archivos de LSM y se exponen al modelo como contenido de imagen MCP nativo; no están integrados en la respuesta JSON del trabajador.
