<!-- i18n-source-sha256: d33afa60bf803b367c950dbadf80fa77167568a970adcac204cdea7e9e965e45 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Agentes e Habilidades

## Quando criar um Agente?

O chat direto é útil para perguntas ou tarefas que são realizadas apenas uma vez. Um “Agente” é uma configuração salvável que pode ser selecionada repetidamente, utilizada em chats programados ou delegada a outros agentes. Vários Agentes podem usar diferentes canais, modelos, instruções e políticas de acesso. Eles compartilham o mesmo Controlador, mas não necessariamente o mesmo escopo de memória ou ferramentas.

## Configure um Agente

Gerencie o Agente pela interface WebUI. Crie um Agente, dê-lhe um nome reconhecível e escolha seu modelo. Escreva as instruções necessárias para descrever a tarefa, o resultado desejado, as restrições e os requisitos de verificação. Configure as capacidades necessárias para o Agente. Depois, salve e inicie uma nova conversa com ele.

![Agent Builder com instruções, ferramentas, aprovação e configurações de habilidade](../assets/chat/agent-builder.png)

Por exemplo, um revisor de repositórios pode ter essas instruções:

```text
Reverifique as mudanças em comparação com a versão principal atual.
Verifique o repositório e os resultados dos testes antes de tirar conclusões.
Não edite arquivos, não envie commits ou implemente nada.
Comunique descobertas concretas, juntamente com as caminhias e evidências relacionadas.
```

As instruções são úteis para orientar o comportamento dos usuários, mas não constituem uma limitação para a autorização de acesso. Defina o acesso à máquina como somente leitura, e ignore as funcionalidades externas desnecessárias, caso o revisor não queira modificar nada. Veja [Ferramentas e permissões](permissions.md).

É melhor ter agentes separados para desempenhar funções distintas, como revisão de código, implementação e operações. Dê a cada agente o acesso mínimo necessário, além de um modelo adequado à sua função. Se um agente não puder iniciar suas tarefas, verifique o canal e o modelo utilizados por ele, antes de alterar configurações irrelevantes.

## Skills

Os pacotes de habilidades contêm instruções reutilizáveis e arquivos relacionados, geralmente com um arquivo chamado `SKILL.md`. As habilidades podem ser gerenciadas na interface web; as habilidades relevantes podem ser ativadas e disponibilizadas para o Agente ou para chat. O modelo pode descobrir e carregar o conteúdo das habilidades quando necessário. Uma habilidade pode descrever um fluxo de trabalho, fornecer exemplos ou conter scripts. No entanto, ela não executa scripts automaticamente nem concede permissões adicionais ao sistema.

Verifique as habilidades importadas antes de ativá-las. Trate as instruções e arquivos relacionados a essas habilidades como qualquer outro código ou prompt fornecido por terceiros. Deve-se garantir que os nomes e descrições das habilidades sejam suficientemente específicos, para que o modelo consiga identificá-las. As referências maiores devem ser separadas, e prefira fluxos de trabalho menores, que possam ser utilizados de forma independente. O registro do lado do Controller e as chamadas ao tool são explicados em [Skills](../guides/skills.md).

O contexto automático de habilidades e memórias é capturado em uma imagem, para que seja possível evitar a necessidade de reescrever o prompt do sistema a cada turno. As mudanças no escopo das habilidades podem ser aplicadas imediatamente; use um novo contexto para testar as habilidades recém-editadas. Uma habilidade carregada de forma intencional é diferente da imagem automática inicial.

## Delegação e subagentes

Os agentes podem delegar tarefas limitadas para subagentes, quando essa capacidade estiver disponível. Um subagente pode usar um agente configurado e manter sua própria linha de execução de tarefas. O agente principal coordeniza a tarefa, lê os resultados do subagente e pode continuar com a linha de execução salva pelo subagente. É possível inspecionar as atividades do subagente a partir da conversa realizada pelo agente principal. Essa visão não é um chat independente e editável.

Use a delegação para tarefas separáveis, como revisões independentes, áreas de arquivos separadas ou investigações de diferentes hipóteses. Forneça ao subagente um objetivo concreto, escopo e resultado esperado. Evite escritas concorrentes nos mesmos arquivos, a menos que a tarefa seja claramente coordenada.

A delegação deve permanecer dentro dos limites de execução autorizados pelo pai. Não é permitido o acesso a máquinas ou serviços MCP que o pai não possa utilizar. A política de aprovação da criança não pode enfraquecer a política do pai. As tarefas da criança podem consumir tokens e tempo de forma independente. Portanto, é necessário inspecionar suas atividades e resultados ao avaliar os custos e o progresso.

## Ferramentas, ações e artefatos

O Agent Builder exibe sua biblioteca de ferramentas disponíveis e as configurações avançadas. Selecione apenas as funcionalidades de que precisa. Para uma ação HTTP descrita por um esquema OpenAPI, verifique o endereço do endpoint, os requisitos de autenticação e as operações permitidas antes de conectar a ação. As ações podem ter suas próprias políticas de autenticação; uma permissão de máquina não autoriza ou revoga as credenciais da API de terceiros. Verifique a resposta da ação antes de considerar que a mutação remota foi completa.

Para o conteúdo da interface do usuário gerado, configure a renderização do artefato conforme descrito em “[Conversas e projetos”](conversations.md). O código gerado não é uma extensão confiável do Controller.

## Modelos práticos de agentes

- **Investigador de acesso somente leitura:** Verifique os registros e as fontes de dados; compare as evidências; identifique as causas do problema. Não faça nenhuma modificação nos dados originais.
- **Agente de Implementação:** Edite o repositório, execute os testes necessários, faça relatórios sobre as diferenças e os erros não resolvidos. É necessário obter a aprovação para operações sensíveis, se isso for apropriado.
- **Agente de Monitoramento:** Verifica as máquinas especificadas e informa sobre o status, erros e o progresso dos trabalhos realizados. Não reinicia os trabalhos, a menos que seja autorizado explicitamente.
- **Agente de Pesquisa:** Permite a busca na rede, cita documentos originais, distingue evidências das inferências, e utiliza ferramentas mecânicas apenas quando necessário.

Os modelos são instruções, e não configurações pré-definidas. É necessário configurar as permissões e capacidades reais de cada agente, de modo que elas correspondam às suas funções pretendidas.
