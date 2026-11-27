<!-- i18n-source-sha256: 012f0d9f7b350fcf47e3fd6afdf2fc9e7044ff28cb2eca7c029c3d6af35f3b04 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Conversas e projetos

## Criar e continuar uma conversa

Abra uma nova conversa, escolha um canal/modelo ou Agente e insira uma mensagem. O chat é executado no Controller, e as atualizações são transmitidas para o navegador. Recarregar a página ou fechar uma aba não equivale a cancelar a execução da operação. Use o botão “Stop” para interromper a execução, e verifique o status resultante antes de iniciar outra operação.

As conversas salvas mantêm sua associação entre o modelo/Agent associado a elas. É possível mudar o modelo se desejar. Uma conversa não é uma Sessão Lógica: ela contém mensagens do usuário e do modelo associado. Já uma Sessão Lógica, por sua vez, contém objetivos de tarefas, progresso e planos relacionados a ferramentas utilizadas no processo de trabalho. É importante manter os IDs relevantes ao transferir uma tarefa longa.

## Organizar e encontrar trabalho adequado.

Use projetos para agrupar conversas relacionadas e definir as permissões de acesso compartilhadas entre máquinas. Um projeto pode conter várias conversas separadas. Você pode mover ou criar conversas no projeto correto, em vez de assumir que as conversas separadas compartilham todo o seu contexto. O projeto ativo pode informar o Agente sobre a organização da conversa.

As etiquetas classificam as conversas; os marcadores de mensagens apontam para mensagens específicas e permitem a navegação até resultados úteis. Esses recursos são separados do atalho de fixação de conversas. Use títulos de chat, busca, arquivamento e indicadores de mensagens não lidas para manter uma interface de navegação fácil de usar.

O arquivamento move uma conversa para fora da lista normal, sem excluir seu histórico salvo. É possível restaurar essa conversa a partir da interface de arquivamento, quando necessário. Excluir uma conversa é um procedimento destrutivo; não use a exclusão como substituto ao arquivamento. A implementação atual utiliza o formato de estado de conversa do SQLite. Não assuma que o formato antigo de arquivamento do Hosted Chat ainda é utilizado.

## Operações de mensagens e execução de tarefas

Os controles disponíveis para mensagens dependem da mensagem em questão e do seu estado atual de execução. É possível editar ou tentar novamente uma determinada transação, quando apropriado. Além disso, é possível excluir uma transação selecionada se ela não for mais necessária. A exclusão altera o histórico de conversas salvas e pode afetar o contexto posterior. Não é possível reverter comandos do shell, gravações remotas, pushs no Git ou outros efeitos externos.

Ao tentar novamente uma execução que falhou, leia os erros detalhados e verifique primeiro as chamadas à ferramenta que já foram realizadas. Se uma operação de escrita tenha sido bem-sucedida antes da desconexão, verifique o estado externo antes de repeti-la. Se houver mais mensagens em fila ou se outra operação já estiver em andamento, use os controles e informações exibidas, em vez de assumir que várias operações podem ser executadas simultaneamente no mesmo chat. O painel de mensagens em fila permite que você verifique as operações pendentes. O controle de direção tenta fornecer orientação dentro de limites seguros, após as ferramentas que estão sendo executadas terminarem. Nenhuma das operações pode reverter os efeitos das ferramentas já realizadas.

## Anexos, visualizações e artefatos

Use o controle de anexos para carregar arquivos ou imagens compatíveis com o sistema. A implementação do processo de carregamento limita os anexos individuais a 32 MiB. Além disso, os limites impostos pela implementação do sistema podem ser ainda menores. Os arquivos carregados são armazenados no Controller e podem ser referenciados pelo modelo correspondente. A interpretação das imagens requer um modelo e um provedor que aceite entradas de imagem. O carregamento de arquivos não significa a concessão do acesso a arquivos locais ou remotos que não estão relacionados ao modelo em questão.

Ao solicitar um arquivo gerado, especifique o caminho, o formato e o conteúdo desejados. Verifique se o arquivo existe antes de compartilhá-lo. Faça o download ou visualize os anexos e arquivos compatíveis do chat, quando disponíveis. Um arquivo gerado no Worker pode precisar ser transferido para o Controller ou para um link de arquivo adequado. Veja [Links de arquivos](../guides/file-links.md).

A renderização de artefatos pode apresentar React, HTML, SVG, Markdown e Mermaid em um painel lateral, em vez de apenas como código. Nas configurações de artefatos do agente, o modo “Normal” utiliza as instruções padrão; o modo “shadcn/ui” adiciona orientações relacionadas às bibliotecas de componentes; já o modo “Custom” permite a renderização sem as instruções integradas para o artefato. O código gerado ou o conteúdo renderizado deve ser considerado como não confiável. Reverifique-o antes de usá-lo fora da visualização preliminar. As visualizações e downloads baseados em arquivos são distintos dos artefatos de interface do usuário gerados.

Não carregue credenciais, chaves privadas ou documentos que não tenha autorização para enviar ao provedor de modelos selecionado. A exclusão de anexos e de conversas é algo separado da exclusão dos arquivos originais no computador.

## Preferências

As preferências do usuário, como as opções de ferramentas e os atalhos de teclado, são gerenciadas através da WebUI e salvos no servidor onde estão implementados. É possível acessar as Configurações para configurar o comportamento do teclado; também é possível distinguir entre enviar uma mensagem e inserir uma pausa na mensagem. As opções de ferramentas do chat devem ser configuradas separadamente das permissões do agente. Consulte [Ferramentas e permissões](permissions.md) e [Memória e contexto](context.md).
