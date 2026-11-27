<!-- i18n-source-sha256: 8ec601aa8e9c57afef769d8346567626355ccf88e122e3296735b7af3639c562 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat

O LSM WebUI Chat é um espaço de trabalho de agente de IA autônomo, integrado ao Controller. Você pode usar seu próprio endpoint de modelo ou uma conta suportada pelo sistema. Além disso, o modelo tem acesso às suas próprias ferramentas e máquinas. Não é necessário nenhum cliente externo para esse serviço. Os clientes externos ainda podem se conectar ao mesmo Controller de forma independente.

## Como as peças se encaixam entre si

- **Controlador:** O serviço em Python que hospeda o aplicativo web, gerencia as solicitações dos usuários, executa os comandos necessários, planeja o cronograma de execução das tarefas e mantém o estado persistente do sistema.
- **Canal:** Uma conexão da API do modelo, ou uma autorização de conta compatível, com suas próprias credenciais, protocolo, lista de modelos e configurações.
- **Modelo:** É um identificador do modelo dentro de um canal. O mesmo identificador em dois canais não implica necessariamente que se trate do mesmo ponto final.
- **Agente:** Uma configuração reutilizável que combina um modelo, instruções, ferramentas, habilidades e permissões.
- **Conversação:** mensagens salvas, configurações, histórico de execução e associação entre o modelo/Agente e as mensagens enviadas.
- **Projeto:** Um grupo de conversas com padrões compartilhados.
- **Worker**: Um alvo de execução conectado ao lado de saída. Não é um provedor de modelo ou um servidor de bate-papo separado.
- **Sessão Lógica**: É uma identidade de tarefa do lado do instrumento, distinta da ID de conversa. Um chat pode utilizar essa identidade para rastrear objetivos, progressos e o trabalho realizado pelo instrumento.

A API do modelo recebe o contexto visível ao modelo e os resultados dos ferramentas utilizadas. O Controlador executa as ferramentas autorizadas; o modelo não se conecta diretamente a um Worker, nem obtém a chave da API do modelo. O navegador apresenta a conversa e controla o Controlador.

## Escolha um guia.

| Eu quero… | Leia |
|---|---|
| Instale o software, faça login e execute uma tarefa inicial. | [Início rápido](../getting-started/web-workspace.md) |
| Conecte um modelo API ou conta ao sistema. | [Canais e modelos](channels.md) |
| Crie agentes reutilizáveis e delegue tarefas para eles. | [Agentes e habilidades](agents.md) |
| Gerencie chats, arquivos e projetos. | [Conversas](conversations.md) |
| Entenda como o sistema recupera informações do histórico e como os orçamentos são gerenciados. | [Memória e contexto](context.md) |
| Restringir a execução e gerenciar as ferramentas MCP. | [Ferramentas e permissões](permissions.md) |
| Executar tarefas e cronogramas de longo prazo. | [Objetivos e automação](automation.md) |
| Pesquisar na web e ler documentos. | [Pesquisa em rede](../guides/webui-network-search.md) |
| Operar, fazer backup e solucionar problemas relacionados à implantação. | [Administração e resolução de problemas](administration.md) |

## Princípios básicos.

Comece com uma solicitação de acesso restrito, apenas para leitura, em uma máquina conhecida. Verifique o resultado da ferramenta antes de permitir qualquer modificação. Um modelo pode estar incorreto, mesmo quando a ferramenta consegue realizar sua função. As credenciais, o armazenamento de dados, o acesso à máquina e a aprovação da ferramenta são questões separadas; alterar uma delas não garante automaticamente a aprovação da outra. Em particular, um ponto de acesso público deve ser protegido como uma plataforma de execução remota.

Para o caminho de conexão do cliente externo MCP, veja [conectividade do cliente](../clients/connectivity.md). Para os argumentos da ferramenta, veja [referência às ferramentas](../reference/tools.md).
