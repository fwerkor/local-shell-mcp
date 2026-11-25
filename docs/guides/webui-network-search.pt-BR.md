<!-- i18n-source-sha256: 2fb1887d3d0f7ca8ac19f19375829b9269f666b08197e4915c0230669303c8fe -->
# Pesquisa na web e leitura de documentos no WebUI

A pesquisa na web fica ativada por padrão no
chat do WebUI. É possível desativá-la para
cada conversa pelo controle abaixo da caixa
de mensagens; a escolha fica salva naquela
conversa. Não é preciso uma chave de API do
provedor nem acesso ao shell do Worker.

O Agent recebe apenas duas ferramentas de
leitura. `web_search(query)` retorna títulos,
URLs e trechos de resultados públicos. Usa
`ddgs` quando instalado ou, como alternativa,
Bing RSS sem chave. Serviços públicos podem
limitar solicitações ou ficar indisponíveis.

`web_fetch(url, query?, offset?, limit?)` lê
HTML, texto puro, JSON, XML, Markdown e PDF.
Em páginas de resumo do arXiv, tenta primeiro
o texto integral em HTML e depois o PDF, sem
API especializada de artigos.

Na primeira leitura, o texto completo é
guardado no cache privado do Controller, se a
pasta permitir escrita. O cache é separado
por usuário, expira após 24 horas e comporta
até 80 arquivos por pessoa. A resposta inclui
até 8000 caracteres; busca, deslocamento e
limite permitem ler outras partes, até 12000
caracteres por chamada.

O download é limitado a 20 MiB e o texto
extraído a 3 MiB. Redes privadas, credenciais
em URLs, portas fora do padrão e
redirecionamentos perigosos são bloqueados.
As conexões usam somente IPs públicos
validados para evitar ataques de DNS
rebinding.

Os PDFs são processados com PyMuPDF ou, em
alternativa, `pypdf`. Documentos
digitalizados sem camada de texto exigem OCR
e geram erro explícito. A codificação
declarada do HTML é respeitada e formatos não
aceitos são rejeitados.

Os links aparecem no cartão de resultado. As
respostas devem citar as URLs originais e as
páginas do PDF quando possível. Conteúdo
externo não é confiável e não pode substituir
as instruções do usuário nem a configuração
do Agent.

Páginas HTML vazias ou dependentes de JavaScript são tentadas novamente em um novo
contexto Chromium sem interface, se o extra browser e o Chromium estiverem instalados.
Páginas estáticas e PDFs não iniciam o navegador. A renderização usa o mesmo
transporte HTTP restrito a IPs públicos, bloqueia solicitações que não sejam de leitura
e conexões diretas do navegador, com limite de 25 segundos e 128 solicitações.
Login, CAPTCHA ou redirecionamentos não suportados podem impedir a leitura.
Acessos negados e resultados vazios são informados e não entram no cache.
