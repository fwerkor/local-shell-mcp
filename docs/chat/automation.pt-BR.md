<!-- i18n-source-sha256: 01c14c19cf5addf99299993b57542259bcb40bbfb13600758b516a86c89e716b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Objetivos, conversas agendadas e trabalhos de longo prazo

## Escolha o mecanismo correto.

| Mecanismo | Objetivo |
|---|---|
| Geração de conversas comuns. | Resposta ao prompt atual, incluindo chamadas a ferramentas necessárias. |
| Objetivo da conversa. | Continuação de uma sessão lógica ativa, mesmo quando há mudanças no modelo utilizado. |
| Conversas agendadas. | Inicie um agente com um prompt salvado, em uma frequência recorrente. |
| Tarefas persistentes ou de longo prazo. | Execução de comandos independentemente de uma única solicitação do modelo. |
| Subagentes. | Atribua uma tarefa limitada a outro thread de agente. |

A conversa agendada não é um “job” persistente do shell. Uma sessão lógica não é uma conversa ou um processo do sistema operacional. Cancelar essa sessão não significa necessariamente interromper tudo o que foi iniciado com os seus ferramentas.

## Objetivo da conversa.

Para tarefas que exigem tempo de execução longo, peça ao agente que defina um objetivo concreto e mantenha um plano de ação, utilizando as ferramentas da sessão lógica. O plano registra os passos e seus status. A execução do chat pode continuar com o plano ativo, mesmo quando há mudanças no modelo, sem a necessidade de esperar por um novo pedido do usuário ou pelo término do tempo de inatividade da área de trabalho externa.

Verifique o plano e o progresso do trabalho em andamento. É possível pausar, retomar ou cancelar a execução do plano, utilizando os controles disponíveis para isso. A continuação do processo requer que haja um plano ativo e uma execução válida do plano; não se deve continuar com um plano que já foi concluído, bloqueado ou cancelado. Respostas repetidas sem progresso geram uma pausa, em vez de um ciclo infinito (atualmente, após três limites inalterados). Solucione o problema que está impedindo a continuação do trabalho antes de retomá-lo.

Defina os critérios de conclusão. Por exemplo: inspecione o repositório, execute as correções necessárias, execute o conjunto de testes correspondentes e relate quaisquer falhas. Peça ao agente que registre os IDs exatos das commits e os resultados dos testes, em vez de declarar o sucesso apenas com base no próprio plano do agente.

O mecanismo de objetivos do cliente externo do MCP é separado. Para saber mais sobre o fluxo de trabalho de transferência de sessão lógica e espaço de trabalho ao vivo, consulte [Human interface](../guides/human-interface.md).

## Crie uma conversa agendada.

![Barra lateral de chats agendados com um agendamento de exemplo desativado](../assets/chat/scheduled-chats.png)

Abra a gestão do bate-papo agendado. Crie um cronograma com um nome descritivo, um agente salvável, um prompt, fuso horário e frequência de conversas. Selecione o alvo da conversa; opcionalmente, escolha um projeto para iniciar uma nova conversa. Salve e ative o cronograma. Use o controle de execução manual para validar a configuração antes de utilizá-lo.

As cadências suportadas incluem horários diários, dias da semana, semanas, cron de cinco campos e execução contínua. A execução contínua começa após o intervalo configurado; um intervalo zero pode causar um carregamento constante do provedor e da máquina. Os horários recorrentes normais exigem um intervalo mínimo de cinco minutos. Use um fuso horário especifico da IANA, como `Asia/Shanghai` ou `UTC`; verifique o próximo cronograma após salvar as configurações.

Exemplo de cron para 09:00 nos dias úteis:

```text
0 9 * * 1-5
```

Isso utiliza o fuso horário selecionado, mas não necessariamente o fuso horário do sistema do Controlador. Verifique as transições relacionadas ao horário de verão, caso o fuso horário escolhido utilize esse recurso.

## Alvos da conversa

- **Nova conversa a cada execução:** É útil iniciar uma conversa separada para cada ocorrência; isso facilita a análise de relatórios individuais.
- **Reutilizar uma conversa:** crie uma conversa na primeira execução e reutilize essa conversa para futuras ocorrências. Isso é útil para o monitoramento cumulativo.
- **Usar uma conversa existente:** escolha uma conversa que já está em andamento e para a qual serão definidas turnos programados para as respostas.

Uma conversa reutilizada ou já existente pode se expandir e precisar ser compactada. É melhor usar chatings independentes quando o contexto histórico não for necessário. As execuções programadas dependem do agente selecionado e do canal de modelo que ainda esteja disponível e útil para uso.

## Permissões deixadas sem supervisão

A execução agendada pertence ao Controller e utiliza os nomes dos escopos autorizados salvos, em vez de manter um token de login do navegador. Salve ou execute manualmente um agendamento para autorizá-lo quando necessário. Aplicam-se as permissões de máquina do Agent designado; as substituições comuns de máquina do projeto ou da conversa não constituem a política de máquina do agendamento. As restrições do Controller, a autorização salva, as capacidades e as aprovações das ferramentas continuam válidas.

Para servidores MCP externos que exigem autenticação, um login interativo não implica automaticamente uma autorização renovável para execução sem supervisão. Se a interface do agendamento exigir nova autenticação ou acesso sem supervisão, resolva as credenciais específicas do servidor ou remova essa dependência antes de ativar o agendamento. Não reutilize tokens do navegador como substituto.

Use um agente de leitura exclusiva para o monitoramento. Descreva explicitamente os objetos permitidos, as saídas desejadas e as ações que devem ser evitadas. Se uma tarefa agendada requer intervenção humana ou aprovação, verifique as interações em andamento. Não assuma que a execução sem supervisão implica em acesso ilimitado. Um exemplo de prompt de monitoramento:

```text
Verifique o trabalho de treinamento especificado, bem como os registros relacionados a esse processo.
Relate o passo atual, as perdas, a taxa de transferência de dados, o prazo de entrega estimado e qualquer erro novo que ocorra.
Não modifique os arquivos, reinicie a tarefa ou inicie novos trabalhos.
Se os dados não estiverem disponíveis, indique o motivo exato pelo qual eles não podem ser obtidos.
```

## Ciclo de vida e recuperação

O Controller gerencia as programações, os estados de execução e as transações relacionadas às ocorrências, de forma transacional. Isso evita que haja repetições de tarefas. Não é necessário que uma guia do navegador permaneça aberta. Não assuma que as ocorrências perdidas serão sempre reproduzidas ou que todo o trabalho externo permanecerá ativo mesmo após a reinicialização do Controller. Verifique a última execução, a próxima execução, as tarefas em andamento e o chat associado após um período de inatividade.

Desative um cronograma para evitar que ocorram eventos automáticos no futuro. Verifique cada evento que já está em execução separadamente. Interromper o cronograma não garante que uma tarefa ou processo seja cancelado. Remova os cronogramas que não são mais necessários e revogue as permissões do Agente que não são mais úteis.

Um trabalho ou terminal criado por um WebUI Agent pode continuar a funcionar mesmo após a conclusão da resposta ao modelo. Além disso, o reinício do Controller não garante necessariamente o término do trabalho realizado pelo agente. Um cancelamento explícito, a perda dos direitos da máquina ou o vencimento dos privilégios podem causar o cancelamento dos trabalhos realizados pelo agente. Se o trabalhador estiver offline, o cancelamento pode permanecer pendente até que o trabalho possa ser entregue. É necessário verificar o próprio trabalho ou terminal antes de declarar que a execução foi interrompida. O agente só pode enviar ou interromper os trabalhos realizados por meio da ferramenta WebUI. Os clientes externos MCP mantêm sua semântica nativa.

As ferramentas de fundo do agente e as tarefas dos subagentes têm seu próprio ciclo de vida. Um resultado pode permanecer pendente de entrega, mesmo após a conclusão da execução da tarefa. Verifique o painel de tarefas de fundo da conversa e colete o resultado. Ou deixe que o processo de wakeup configurado continue para que a tarefa pai continue a ser executada. Não inicie uma tarefa duplicada simplesmente porque o resultado ainda não está visível.

Para comandos que devem durar mais do que uma única solicitação de ferramenta, use trabalhos rastreados pelo LSM ou terminais persistentes. Salve o resultado em um arquivo de log, registre os identificadores dos trabalhos e verifique o progresso real. Veja [Padrões de uso](../guides/usage-patterns.md).
