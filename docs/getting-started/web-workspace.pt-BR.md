<!-- i18n-source-sha256: 01cf883cb71925e93fabc21d32315ef8c869ee2ea548e54a0347e2f6b730a327 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Início rápido do chat WebUI

O espaço de trabalho unificado da LSM integra o chat inteligente, os projetos, os agentes e as páginas operacionais do controlador. Ele é executado pelo controlador Python, que utiliza sua autenticação e banco de dados SQLite para seu funcionamento. Não é necessário um servidor de chat separado. Clientes externos como [ChatGPT](chatgpt-connector.md) e [Gemini](gemini-spark.md) continuam a ser suportados.

## 1. Iniciar o Controller

Siga o [instruções de inicialização](quickstart.md) para o ambiente de execução que você preferir. Verifique se a WebUI está ativada e utilize armazenamento persistente. Os valores padrão são os seguintes:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

Após exportar o seu ambiente de serviço, inicie o Controller.

```sh
local-shell-mcp --mode mcp
```

Para a liberação em fila única, utilize o executável baixado. O Controller instalado serve como interface para o frontend compilado; o conjunto de ferramentas de desenvolvimento JavaScript é necessário apenas para a construção do código fonte. Veja as instruções de construção do WebUI em [WebUI build instructions](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## 2. Abrir o espaço de trabalho no navegador

Abra o endereço `http://127.0.0.1:8765/ui` a partir do host do Controller, ou o URL HTTPS configurado, que termina em `/ui`. Faça login com a autenticação LSM configurada para aquela implantação. Use o protocolo HTTPS autenticado para acesso remoto. As páginas de chat e controle compartilham a mesma origem.

## 3. Adicionar um canal de modelo

Abra o seletor de modelos e a ferramenta de gerenciamento de canais. Adicione um canal da API ou conecte uma conta compatível com o OpenAI. Para um endpoint típico compatível com o OpenAI, insira o nome do canal, selecione “Chat Completions”, insira o URL base da API e as credenciais necessárias. Também é possível encontrar modelos ou fornecer um ID de modelo conhecido. Salve a configuração e selecione um modelo.

Para um serviço de inferência local, use um endereço acessível a partir do Controlador, e não apenas pelo seu navegador. Por exemplo, `http://127.0.0.1:8080/v1` é um endereço adequado, caso o serviço de inferência esteja atuando nesse endereço dentro do espaço de nome da rede do Controlador. Para mais informações sobre protocolos, autorização de usuários, descoberta de modelos e limites de contexto, consulte [Channels and models](../chat/channels.md).

## 4. Executar uma primeira tarefa

Inicie uma conversa e faça uma pergunta simples para testar a conectividade do modelo. Depois, tente usar um ferramenta de leitura apenas.

```text
Liste os arquivos na raiz do espaço de trabalho do Controller.
Diga-me qual máquina você inspecionou e resuma o resultado.
Não modifique os arquivos ou execute nenhum comando que implique na escrita de dados nos arquivos.
```

Verifique o resultado real do instrumento utilizado. Se algum instrumento estiver faltando, verifique as configurações relacionadas aos instrumentos no chat, as configurações do agente e as permissões da máquina. Use um agente salvo para tarefas recorrentes e configure seu acesso de forma explícita. Veja [Instrumentos e permissões](../chat/permissions.md).

![Chat via WebUI com uma conversa de demonstração](../assets/chat/chat-workspace.png)

As capturas de tela deste guia e das páginas seguintes foram obtidas em um Controller isolado, com um modelo de demonstração. Essas capturas não contêm credenciais de produção ou conversas reais. As etiquetas da interface do usuário em inglês podem diferir das etiquetas no idioma selecionado.

## 5. Explorar o espaço de trabalho

| Área | Para que serve esse produto? |
|---|---|
| Chats e projetos | Iniciar e pesquisar chats, organizar projetos, tags e marcadores de mensagens |
| Agents | Modelos, instruções e configurações de ferramentas reutilizáveis |
| Memória e Habilidades | Gerenciar conhecimento e instruções reutilizáveis |
| Chats agendados | Execute o Agente salvo com um prompt recorrente. |
| Arquivos e terminais | Verifique ou execute operações nos ambientes Controller e Worker. |
| Desktop | Inspecionar e controlar sessões GUI remotas suportadas |
| Sessões, tarefas e auditoria | Verificação das tarefas duradouras, do progresso da execução e das atividades dos instrumentos utilizados. |
| Máquinas e dispositivos externos MCP | Gerenciar trabalhadores e servidores MCP aninhos |

O conjunto exato de controles depende da sua implementação, dos seus contas e das capacidades ativadas. Fechar o navegador não cancela automaticamente a geração de dados no lado do servidor; use o comando “stop” quando precisar interromper o trabalho.

## Passos seguintes

Leia o [Guia de Chat WebUI](../chat/index.md) para conhecer todo o fluxo de trabalho. Para informações sobre configuração, backup e recuperação de erros, consulte [Administração e solução de problemas](../chat/administration.md).
