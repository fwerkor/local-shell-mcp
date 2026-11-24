<!-- i18n-source-sha256: 78ec7a5b5dc75473db69b12cf1626f81c3071f52661bf1023047af5d6d24e3ee -->
# Búsqueda web y lectura de documentos en WebUI

La búsqueda web está activada de forma
predeterminada en el chat de WebUI. Puedes
desactivarla para cada conversación con el
interruptor situado bajo el cuadro de
mensaje. La elección se guarda en esa
conversación. No se necesita una clave API
del proveedor ni permisos de shell del
Worker.

El Agent recibe solo dos herramientas de
lectura. `web_search(query)` devuelve
títulos, direcciones URL y fragmentos de
resultados públicos. Utiliza `ddgs` si está
instalado y, en caso contrario, intenta Bing
RSS sin clave. Los servicios públicos pueden
limitar el tráfico o no responder.

`web_fetch(url, query?, offset?, limit?)` lee
HTML, texto sin formato, JSON, XML, Markdown
y PDF. Para un resumen de arXiv intenta
primero el texto completo en HTML y, si no
existe, el PDF. No utiliza ninguna API
especializada de artículos.

La primera consulta guarda el texto completo
en la caché privada del Controller si es
escribible. La caché está separada por
usuario, dura 24 horas y permite 80 archivos
por usuario. Una respuesta incluye como
máximo 8000 caracteres; puedes continuar por
desplazamiento, límite o consulta, hasta
12000 caracteres por llamada.

La descarga tiene un límite de 20 MiB y el
texto extraído de 3 MiB. Se rechazan redes
privadas, credenciales dentro de direcciones
URL, puertos no estándar y redirecciones
inseguras. Las conexiones solo se realizan a
IP públicas verificadas para evitar el
reenvío DNS malicioso.

Los PDF se procesan con PyMuPDF y, como
alternativa, `pypdf`. Los documentos
escaneados sin capa de texto necesitan OCR y
producen un error explícito. El HTML respeta
su codificación declarada y se rechazan los
formatos no compatibles.

Los enlaces aparecen en la tarjeta de
resultados. Las respuestas deben citar las
URL originales y las páginas del PDF cuando
sea posible. Los resultados externos no son
fiables y sus instrucciones nunca sustituyen
las instrucciones del usuario ni la
configuración del Agent.
