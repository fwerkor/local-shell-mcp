<!-- i18n-source-sha256: e5ebd5f8cfb42332f4e38d63eabe47a6274ceacf919130202203bd85917f3469 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Ferramentas, máquinas e permissões.

## Camadas de autorização.

O instrumento listado não garante a permissão para sua execução. A autorização efetiva envolve restrições do Controlador, escopos do usuário autenticado, políticas da máquina, capacidades do agente e aprovação do instrumento. As instruções simples não são suficientes para garantir o acesso ao instrumento.

As máquinas registradas, incluindo o destino local do Controller, quando ativado, têm como padrão a capacidade de ler/gravar dados na política da máquina de chat. No entanto, é necessário restringir esses padrões para implantações sensíveis. Nomes de máquinas desconhecidos não recebem permissões implícitas. O Controller pode desativar a execução local ou remota dos trabalhadores, independentemente um do outro.

## Acesso à máquina

| Acesso | Significado |
|---|---|
| Nenhum | As operações da máquina não estão disponíveis. |
| Somente leitura | São permitidas apenas as operações classificadas como somente leitura; a execução de comandos shell/Python não é considerada uma operação somente leitura. |
| Ler/escrever | Permite operações de leitura, modificação e execução autorizadas, mas com outras restrições. |
| Herdar | Utilize o padrão mais alto aplicável, em vez de uma sobreposição explícita. |

![Permissões e modo de aprovação da máquina em uma conversa](../assets/chat/machine-permissions.png)

Defina os padrões globais e as substituições por projeto e por conversa nos controles de permissões de máquina. As substituições de uma conversa prevalecem sobre as do projeto, que prevalecem sobre os padrões globais. Um Agent pode limitar ainda mais o acesso por máquina ou por sua política padrão; suas permissões explícitas não contornam as restrições do principal autenticado nem do Controller.

Exemplo: uma política global de leitura e escrita, uma substituição do projeto de somente leitura e um Agent com permissão de leitura e escrita resultam em acesso de somente leitura na conversa desse projeto, salvo substituição explícita pela política da conversa. Uma substituição de leitura e escrita na conversa ainda não pode ultrapassar o limite de somente leitura do Agent.

A execução programada com um Agente nomeado utiliza a política de máquina desse Agente, além dos escopos de execução salvos por ele. Isso significa que o Agente não herda as configurações padrão da máquina de chat. Veja [Objetivos e automação](automation.md). Use um Agente dedicado para tarefas que não precisam de intervenção humana.

## Aprovação do instrumento

| Moda | Comportamento |
|---|---|
| Automático | As chamadas realizadas com o instrumento autorizado continuam sem a necessidade de um processo de aprovação adicional, a menos que uma política específica exija isso. |
| Revise operações arriscadas | O Controller solicita revisão para operações classificadas como perigosas, incluindo comandos shell arbitrários e muitas chamadas externas. |
| Revise todas as ferramentas | É necessário solicitar aprovação para chamadas de ferramentas comuns. |

As configurações de aprovação da conversa podem herdar os padrões do Agent e os globais. Regras explícitas de negação ou aprovação existentes continuam válidas. Um Agent filho não pode tornar o modo de aprovação do pai menos restritivo. A aprovação é independente das permissões: aprovar uma ação de máquina negada não concede acesso à máquina.

Reveja os argumentos reais, o destino e os possíveis efeitos colaterais antes de aprovar. Para um fluxo de trabalho não supervisionado, configure o agente e a política de aprovação com cuidado; a necessidade de aprovação por parte de uma pessoa pode atrasar o processo. Não amplie o acesso apenas para eliminar os prompts.

## Ferramentas MCP nativas e externas

As ferramentas nativas operam no Controller e nos Workers registrados, por meio do LSM. O registro de ferramentas inclui operações com arquivos, shell e tarefas, operações com navegadores e interfaces gráficas, descoberta remota, sessões lógicas e outras funções. Para saber os esquemas exatos de argumentos, consulte [Referência às ferramentas](../reference/tools.md). Para conectar máquinas, consulte [Workers remotos](../guides/remote-workers.md).

Gerencie servidores MCP aninhados no WebUI. As configurações suportadas incluem transporte de dados local e HTTP remoto, com variáveis de ambiente ou cabeçalhos específicos para cada servidor. Ative a capacidade externa do MCP no chat e no agente correspondente. O agente pode descobrir, inspecionar e chamar ferramentas externas disponíveis; sua autorização e aprovação continuam aplicáveis.

Uma ferramenta MCP externa pode operar independentemente das ACLs nativas de máquina: uma API externa remota pode modificar recursos mesmo quando o acesso às máquinas locais está desativado. Revise separadamente as permissões e as credenciais do serviço externo. Não instale servidores stdio não confiáveis em um Controller que contenha arquivos confidenciais.

## Pedir ao usuário e ativar/desativar funcionalidades

O “Ask User” permite que o Agente solicite informações de forma estruturada, em vez de tentar adivinhar as respostas. A resposta é dada com base na pergunta apresentada. Trata-se de uma solicitação de informações, e não de um pedido para contornar um recurso que foi negado. Quando a tarefa não é atendida por conta própria, é necessário instruir o Agente sobre como lidar com as situações incertas e verificar as interações pendentes antes de assumir que a tarefa foi concluída.

O compositor exibe os controles relacionados às funções disponíveis para o modelo. Esses controles incluem a busca na rede, o MCP externo e a memória utilizada pelo modelo. Esses controles determinam quais recursos estão disponíveis para o modelo. Eles são separados da autorização de acesso aos recursos. Desativar uma função não elimina os resultados históricos obtidos com essa função. A busca na rede está ativada por padrão, e utiliza ferramentas de leitura exclusiva, conforme descrito em [Busca na rede](../guides/webui-network-search.md).

## Auditoria e verificação

Verifique os chamados do instrumento e seus resultados no chat; expanda os detalhes quando estiver diagnosticando falhas. O registro de auditoria do Controller mostra as atividades do instrumento nativo, e as tarefas/sessões exibem a execução em andamento. Um resultado bem-sucedido da API significa que o instrumento retornou um resultado, mas isso não garante que a operação externa solicitada tenha alcançado seu objetivo. Verifique os dados de escrita, o status das tarefas remotas e a saúde da implantação de forma independente. Veja [Registro de auditoria](../guides/audit-log.md).
