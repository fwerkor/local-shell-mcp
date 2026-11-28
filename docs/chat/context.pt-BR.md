<!-- i18n-source-sha256: 214687d6067b7dc2dd2b6eec1a207aa50be3ab9550d081f8a60e3013684c0250 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Memória, contexto e uso do token

## Três tipos diferentes de estados

| Estado | Objetivo |
|---|---|
| Histórico de conversas | As mensagens originais e as atividades relacionadas aos ferramentas são salvos pelo Controlador. |
| Janela de contexto | O subconjunto de instruções, esquemas de ferramentas, histórico, resumos e outros dados enviados em uma solicitação de modelo específica. |
| Memória persistente | Fatos e preferências que podem ser reutilizados em diferentes conversas, dentro do escopo da memória relacionada. |

Uma conversa que foi salva por muito tempo pode exceder a capacidade da janela de contexto do modelo, sem que toda a história da conversa seja perdida. A memória não significa que toda a história da conversa seja enviada para cada solicitação feita pelo modelo.

## Gerenciar memória

![Barra lateral de gerenciamento de memória com um registro de exemplo](../assets/chat/memory-management.png)

A memória é ativada por padrão, a menos que seja desativada pelas configurações do usuário, pela opção de chat ou pelas restrições relacionadas à capacidade de implantação do agente. Use a página de gerenciamento de memória para inspecionar e editar as informações armazenadas. Peça ao agente que memorize fatos úteis, convenções de projeto ou preferências, e verifique o resultado na interface de memória.

Ao editar uma entrada de memória, use uma chave que contenha apenas letras minúsculas e sublinhados (por exemplo, `repository_conventions`). O limite de comprimento padrão é de 10.000 caracteres; uma instalação pode configurar seus próprios limites para o armazenamento de informações na memória. Se uma entrada for rejeitada, verifique o erro, em vez de dividir as informações secretas em várias chaves.

A memória pode utilizar um pool de dados compartilhado entre todos os agentes, ou um escopo específico para cada agente, dependendo da configuração do agente em questão. Não armazene chaves de API, senhas ou outros dados sensíveis na memória. Desativar a memória impede que esses dados sejam utilizados no escopo correspondente. Isso não significa que as entradas armazenadas sejam excluídas ou que as menções feitas durante a conversa sejam removidas.

Quando exposto ao ambiente de execução, o modelo utiliza a função `set_memory` para criar ou atualizar entradas no banco de memória. Um valor vazio remove essa entrada. A função `find_memory` recupera as entradas com base em consultas ou chaves exatas. Uma consulta vazia lista todas as memórias salvadas. O sinalizador opcional `include_conversations` permite que textos de outras conversas também sejam considerados na busca. A paginação utiliza os parâmetros `page` (padrão: 1) e `limit` (padrão: 10; máximo: 50). Essa recuperação de histórico analisa o texto das conversas, em vez dos registros brutos da execução das ferramentas. A recuperação é feita com base na relevância dos dados, portanto, use nomes ou termos precisos e refine a consulta, se necessário.

A injeção automática de memória/habilidades permanece constante ao longo das conversas, para que os prefixos dos prompts do provedor possam ser reutilizados. Editar a memória armazenada não altera o estado do snapshot já injetado. A recuperação explícita da memória permite o acesso aos dados armazenados atualmente; uma nova conversa pode ser iniciada, caso seja necessário um novo contexto para a conversa.

## Capacidade de contexto

Defina o limite de contexto real de cada modelo em seu canal correspondente. O Controller estima a entrada visível do modelo e reserva espaço para a saída; a implementação atual do orçamento utiliza uma proporção de compactação de 85% e uma proporção de reserva de 5%. Esses valores podem ser aproximados, especialmente quando se trata de um tokenizer desconhecido, de solicitações multimodais ou de esquemas específicos do provedor.

A composição do contexto pode incluir instruções do sistema, configurações do Agent, definições de ferramentas, anexos, mensagens anteriores e resultados das ferramentas. Um provedor pode usar um tokenizer diferente ou contar tokens internos adicionais. Trate a exibição como uma orientação operacional, e não como uma garantia de funcionamento do provedor.

## Compactação automática

Quando o orçamento do contexto requer compactação, o Controller cria ou atualiza um resumo dos dados do contexto anterior, mantendo assim a história recente para solicitações subsequentes do modelo. O resumo tenta preservar os objetivos, restrições, decisões, progressos, identificadores relevantes, resultados das ferramentas e próximas ações. A história original permanece disponível para inspeção; o resumo é uma aproximação gerada pelo modelo, e não uma reprodução perfeita.

A compactação é realizada antes do próximo pedido, o que reduz o tamanho do contexto utilizado pelo modelo. Se a compactação falhar, o motor tenta novamente, de acordo com seu mecanismo de tratamento de erros. Não se deve continuar com o processo utilizando um input já de tamanho excessivo. Verifique o status da compactação e os erros detalhados, caso o processo não possa continuar. As mensagens recentes e as relações entre ferramentas e resultados devem permanecer coerentes. Os resultados das ferramentas já concluídos não devem ser reescritos constantemente apenas para reduzir o tamanho do contexto.

Um único arquivo ou resultado da ferramenta pode ainda ultrapassar o orçamento estipulado. Solicite um resultado limitado, intervalos de arquivos ou um resumo do conteúdo. Salve os resultados grandes em arquivos e recupere partes específicas, em vez de inseri-las repetidamente no contexto do modelo.

## Uso cumulativo e número de hits no cache

A exibição do uso da sessão e a janela de contexto respondem a questões diferentes. O uso de entrada/saída acumula-se ao longo dos pedidos, incluindo contextos repetidos. As métricas de cache descrevem o armazenamento em cache dos dados fornecidos pelo provedor, quando disponíveis. A ocupação do contexto mede o tamanho da janela ativa do modelo, e não soma todos os pedidos anteriores.

Por exemplo, um pedido que contém 20.000 tokens de entrada, seguido por outro pedido que contém 25.000 tokens de entrada, consumirá um total de 45.000 tokens de entrada. No entanto, o segundo pedido utilizará aproximadamente 25.000 tokens da capacidade atual do contexto do modelo. Os tokens armazenados em cache não são gratuitos, a menos que o provedor especifique o contrário. Uma maior capacidade do modelo altera a capacidade disponível, mas não afeta o uso já consumido anteriormente.

A compactação pode reduzir a ocupação atual do espaço, ao mesmo tempo em que aumenta o consumo do modelo. A mudança de modelo altera as limitações do contexto aplicável; no entanto, o consumo anterior não é apagado. Se um provedor omitir informações sobre o uso real ou os metadados do cache, as estimativas e métricas podem ser incompletas. Para fins de reconciliação financeira, use os dados de faturamento e preços do provedor, e não apenas o display LSM.

## Reduzir custos e preservar informações úteis.

Mantenha as instruções do agente estáveis. Evite o uso de resultados de ferramentas desnecessários e utilize métodos de recuperação eficazes. Inicie conversas separadas para trabalhos não relacionados. Quando for necessário realizar a transferência de tarefas, salve um arquivo com informações precisas, incluindo caminhos exatos, IDs de compromissos, resultados observados e questões pendentes. Verifique as informações importantes em comparação com a fonte original ou com os resultados da ferramenta. Não confie apenas no resumo gerado pela ferramenta.
