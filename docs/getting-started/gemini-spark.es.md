<!-- i18n-source-sha256: b7c3dfd7dc21a498f8410a88a8a52094ca0349856dfa43d267e3fe7bb273685a -->
# Conecte Gemini Spark / Aplicaciones personalizadas

La función **aplicaciones conectadas personalizadas** de Gemini (anteriormente descrita como **Spark**) permite a un usuario elegible de Gemini conectarse a un servidor MCP remoto. LSM puede proporcionar el punto final MCP. Esta es una **conexión de cliente alternativa** para [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) y otros clientes MCP; no reemplaza ni implementa el controlador LSM.

Actualmente, Google restringe las aplicaciones personalizadas a **usuarios mayores de 18 años en los Estados Unidos**, que hayan iniciado sesión con una **cuenta personal de Google** y **Mantener actividad habilitada**. La función está disponible en **inglés**. Las conexiones deben crearse en la aplicación web Gemini, aunque las aplicaciones conectadas se pueden utilizar posteriormente en el móvil. Las etiquetas de disponibilidad y UI pueden cambiar; consultar el [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

## Antes de conectar

- Inicie un tiempo de ejecución de LSM, por ejemplo con [Docker Compose](../installation/docker.md), y verifique su estado.
- Exponga su punto final MCP a través de **HTTPS accesible públicamente** y mantenga OAuth habilitado.
- Conozca los detalles de autenticación del Controlador y apruebe solo los alcances que necesite.
- Utilice un espacio de trabajo o contenedor restringido. Gemini podrá solicitar operaciones con efectos reales sobre ficheros, máquinas y terminales.

El punto final para entrar en Géminis es:

```text
https://your-public-host.example.com/mcp
```

No ingrese a la interfaz de usuario web (`/ui`), la URL de LibreChat o el origen del sitio sin `/mcp`. Las implementaciones públicas no deben deshabilitar la autenticación para evitar errores de conexión.

## Conéctate en Géminis

1. En una computadora, abra [Gemini](https://gemini.google.com/) e inicie sesión con una cuenta personal elegible.
2. Abra **Configuración y ayuda → Aplicaciones conectadas**. Dependiendo de la interfaz actual, puede estar en **Inteligencia personal → Aplicaciones conectadas**.
3. En **Aplicaciones personalizadas**, seleccione **Agregar una aplicación personalizada** o use el campo URL de la aplicación personalizada.
4. Pegue la URL LSM HTTPS `/mcp` y luego elija **Siguiente**.
5. Complete el flujo de consentimiento y OAuth con el controlador LSM. LSM admite el descubrimiento de OAuth y el registro dinámico de clientes. Si Gemini solicita credenciales de cliente OAuth manuales, verifique sus opciones avanzadas y la configuración de LSM OAuth antes de continuar.
6. En una conversación de Gemini, escriba `@` y seleccione la aplicación personalizada conectada para solicitar una herramienta LSM.

Comience con: "Utilice la aplicación LSM conectada para inspeccionar el entorno y enumerar los archivos del espacio de trabajo. No modifique nada". Verifique los resultados de la herramienta y la auditoría del controlador antes de intentar operaciones de escritura.

## Límites y solución de problemas

- **Sin opción de aplicaciones personalizadas:** confirme la elegibilidad de la cuenta, región, edad, idioma y Keep Activity. Esta es una restricción de disponibilidad del lado de Gemini, no un error de configuración de LSM.
- **La URL se rechaza:** use un punto final HTTPS `/mcp` accesible externamente; verifique el descubrimiento de OAuth y su proxy inverso.
- **OAuth falla:** verifique la pantalla de autorización de LSM, el registro del cliente, la URL de devolución de llamada y los alcances concedidos. No publique un punto final MCP no autenticado.
- **Falta una herramienta o falla:** la compatibilidad con la herramienta/esquema MCP del lado del cliente puede variar. Pruebe una llamada simple de solo lectura e inspeccione los registros y la auditoría de LSM; No se garantiza la compatibilidad total con todas las funciones del cliente Gemini.
- **Desconexión:** regrese a **Aplicaciones conectadas** para deshabilitar, desvincular o eliminar LSM cuando ya no sea necesario.

[official guide](https://support.google.com/gemini/answer/17209137) de Google describe el flujo y la disponibilidad de las aplicaciones personalizadas más recientes. Para obtener una integración Gemini local basada en CLI, consulte [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). El LSM [ChatGPT connector tutorial](chatgpt-connector.md) sigue estando disponible de forma independiente.
