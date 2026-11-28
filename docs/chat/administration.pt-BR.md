<!-- i18n-source-sha256: 91fa7e8e41354be2761864ffe05d1efb85063953c79a40065ad61661cc15b836 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Administração e resolução de problemas.

## Arquitetura de implantação.

O frontend WebUI é servido pelo Controller em Python, no mesmo local dos endpoints REST e MCP. O backend padrão utilizado é o SQLite. Os arquivos binários lançados incluem os recursos necessários para o funcionamento do frontend. Para construir o frontend a partir da fonte do código, é necessário usar a cadeia de ferramentas de compilação JavaScript. Não é necessário instalar o Controller no sistema. Node.js, MongoDB, Meilisearch e o backend LibreChat, que são implementados separadamente, também não são necessários.

Use as instruções de [Início Rápido](../getting-started/quickstart.md) e [Referência de Configuração](../reference/configuration.md). Para builds de código fonte, consulte as instruções de construção no [WebUI](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## Garanta a segurança da implantação.

Use um proxy reverso HTTPS confiável ou um túnel de comunicação seguro. Mantenha o Controller dentro de um container ou máquina virtual adequada. Limite o acesso recebido e proteja as credenciais de saída. Não exporte um endpoint de execução não autenticado na Internet pública.

O proxy deve suportar a transmissão de respostas sem necessidade de armazená-las em buffer até sua conclusão. Também é necessário suportar atualizações do protocolo WebSocket para interfaces que exigem isso. Use tempos de espera adequados para solicitações longas e permita tamanhos de arquivos de upload permitidos. Mantenha o URL público configurado consistente com o local do navegador e os retornos OAuth. Não corrija falhas no TLS desativando globalmente as verificações de certificados.

As solicitações de modelo são enviadas ao Controller. As mensagens visíveis para o modelo, os anexos e os resultados dos ferramentas podem ser enviados à API selecionada. É necessário avaliar os termos de tratamento de dados do provedor antes de utilizar conteúdo confidencial. Além disso, é importante proteger as informações secretas do MCP e os tokens de convite do Worker.

## Estado, backup e atualização

O diretório padrão é `.local-shell-mcp`, localizado dentro do espaço de trabalho configurado. O valor `LOCAL_SHELL_MCP_STATE_DIR` pode ser alterado. A base de dados compartilhada é `lsm.sqlite3`. Conversas, projetos, configurações, Agentes, memória, cronogramas e estado de execução são armazenados no servidor. Arquivos anexos, arquivos do espaço de trabalho e outros dados podem estar fora da base de dados.

Faça cópias de segurança do diretório estadual completo, bem como das configurações do estado fora dele. Também faça cópias de segurança do ambiente de implantação e dos arquivos relevantes do workspace. Trate as cópias de segurança como algo importante. Uma cópia de segurança apenas do banco de dados pode omitir anexos ou configurações. Use um mecanismo de backup consistente, como o Controller, ou um mecanismo de backup baseado no SQLite. Copiar apenas o arquivo principal do banco de dados SQLite pode omitir o conteúdo WAL comprometido. Verifique as cópias de segurança restaurando-as em um ambiente de teste isolado.

Antes de realizar uma atualização, registre a versão atual do sistema, o caminho de execução, as configurações, a localização dos dados e as tarefas ativas em execução. Interrompa ou desative as tarefas relevantes, faça um backup consistente, atualize a instalação do sistema e verifique a autenticação, o histórico de conversas, a geração de modelos, o streaming, os trabalhadores e as tarefas agendadas. A migração do SQLite para uma versão mais recente é suportada na inicialização; preserve os arquivos antigos até que a migração seja verificada. Não substitua o diretório de dados de produção por um diretório de teste vazio.

O rollback não consiste simplesmente em alterar o arquivo binário, caso haja mudanças no estado de persistência do banco de dados durante a migração. É necessário restaurar o estado compatível quando necessário, evitando assim a execução de dois controladores configurados separadamente no mesmo armazenamento.

## Diagnóstico do problema relacionado ao chat que falhou.

| Sintomas. | Verificar primeiro. |
|---|---|
| Não é possível carregar a interface do usuário. | Processamento pelo controlador, pacote de front-end, URL correta, proxy e autenticação |
| Faltando o modelo. | Configuração do canal, identificação do modelo, ID do modelo, autorização do usuário. |
| Erro HTTP 401/403 do provedor. | Chave da API/usuário, permissões do provedor, canal selecionado e protocolo. |
| HTTP 429 | Limites de taxa/quota, solicitações concorrentes, status do usuário/plano. |
| HTTP 400/413/422 | Compatibilidade das solicitações, tamanho dos dados de entrada, limites de anexos, parâmetros do modelo. |
| Erro HTTP 5xx ou tempo limite de espera. | Estado do provedor, rede, capacidade de serviço do modelo, tempo limite do proxy. |
| A transmissão de dados é interrompida. | Reconexão/recarregamento; verificação do status da geração e dos erros detalhados. |
| O tool não está disponível. | Opções de configuração, Capacidades do agente, ACLs da máquina, Escopos do OAuth, Comutadores do controlador |
| O trabalhador está offline. | Registro dos trabalhadores, conexão de saída, registros do Controller |
| A aprovação ou a resolução do problema ainda não foi concluída. | Abra a conversa e verifique a ação solicitada. |
| O cronograma não está sendo executado. | Estado ativado, fuso horário, Agente/canal, destino, autorização salva, última execução |

Não assuma que todos os erros do tipo HTTP vêm da mesma serviço. É necessário distinguir entre falhas no login LSM, erros na API do modelo upstream, erros externos relacionados ao MCP e erros no transporte de dados pelo Worker. Verifique os erros detalhados e os logs relevantes do Controller. Recolha as chaves, tokens de acesso e URLs de retorno de chamadas antes de compartilhá-los.

## Tentativas de recuperação do provedor

Antes de uma resposta do modelo começar, erros transitórios de conexão e determinados erros HTTP (408, 429, 500, 502, 503, 504) podem ser tratados com novas tentativas e espera limitada. Os intervalos normais atuais são de 1, 2, 4, 8, 16, 30, 30 e 30 segundos (oito novas tentativas após a solicitação inicial). HTTP Retry-After pode estender a espera até 120 segundos; certos erros de streaming adicionam variação aleatória. O limite de tentativas se aplica a cada solicitação ao modelo, não à conversa inteira. A compactação tem seu próprio mecanismo de recuperação. Um limite por créditos esgotados pode persistir até o provedor repor a cota. As novas tentativas automáticas não garantem sucesso nem tornam uma assinatura ilimitada.

A interrupção durante o processo de execução difere de um erro que ocorre antes do primeiro evento de resposta. Não se deve confiar na reprodução automática de uma sequência de comandos parcialmente executada. É necessário verificar o histórico salvo e o estado externo antes de tentar novamente. Se o processo ainda estiver ativo, é melhor reconectar, em vez de iniciar um trabalho duplicado. Se o processo terminou com falha, use os controles de recuperação/repetição conforme apropriado, ou inicie um novo chat com uma transferência explícita do controle do processo original, caso este não possa continuar.

Falhas relacionadas à compactação do contexto devem ser investigadas separadamente dos erros comuns na geração de modelos. Verifique o limite de memória efetivo, a compatibilidade dos modelos, os resultados excessivos gerados pelo software e as cotas disponíveis. Veja [Memória e contexto](context.md).

## O que incluir em um relatório de erro?

Informe a versão e o commit do LSM, o método de instalação, o sistema operacional, o protocolo utilizado, o tipo do endpoint sanitizado, o ID do modelo, o horário aproximado, as etapas necessárias para reproduzir o problema, o status das conversas/execuções relevantes e os erros detalhados. No caso de um problema remoto, inclua também a versão do Worker, o nome da máquina e o status do heartbeat/poll. Se possível, incluam-se também exemplos de como o problema pode ser reproduzido. Nunca envie chaves de API, tokens OAuth, prompts privados ou dados pessoais desnecessários.
