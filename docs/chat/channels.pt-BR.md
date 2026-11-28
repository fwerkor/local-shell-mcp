<!-- i18n-source-sha256: a40a962d4db93cc0aac03601ffd13b21ab3a504c9bff930ab4b8173c4cfa4537 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Canais e modelos

## Configurar um canal

Abra o selecionador de modelos no Chat e vá até a seção de gerenciamento de canais. Selecione **Adicionar canal**, escolha o tipo de conexão desejada, insira as informações necessárias e salve. Para criar um novo chat, selecione um modelo desse canal. Para criar um Agente personalizado, selecione o canal e o modelo na configuração do agente.

Os canais são de propriedade do Controller, e não configurações de chat pessoais. Em implantações autenticadas, o gerenciamento de canais requer o escopo `admin:config`. Um administrador pode configurar canais compartilhados sem precisar distribuir chaves de API aos usuários do Chat.

![Adicionar um canal de modelo na caixa de diálogo de configuração do canal](../assets/chat/channel-settings.png)

Um canal normal de API possui nome, protocolo do provedor, URL base, credenciais e identificadores de modelos. Use uma chave de API emitida para o endpoint selecionado, e não a senha da sua conta LSM. O LSM faz solicitações a partir do Controller; um URL que funciona no seu laptop pode não funcionar a partir do Controller.

| Protocolo | Exemplo de URL base de API | Uso |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | Gateways de chat compatíveis com OpenAI e servidores locais de inferência |
| OpenAI Responses | `https://api.openai.com/v1` | Um gateway que exibe o API de Respostas |
| Nativo antrópico | `https://api.anthropic.com/v1` | APIs compatíveis com mensagens antropicas |
| Nativo do Google Gêmeos | `https://generativelanguage.googleapis.com/v1beta` | APIs compatíveis com a função de geração de conteúdo do Gemini |

Use o URL básico exigido pelo provedor, em vez de copiar um URL completo para a solicitação de geração de conteúdo, como um URL que termina em `/chat/completions`. Um gateway que afirma ser compatível com a OpenAI pode suportar a geração de respostas, mas não a utilização de ferramentas, streaming, entrada multimodal ou opções de raciocínio. Escolha o protocolo que realmente é suportado pelo gateway. Os URLs exemplares são apenas exemplos de protocolo, e não garantem acesso gratuito ou disponibilidade.

## Endpoints locais e personalizados

Para um servidor compatível com a OpenAI que esteja conectado ao Controller, o URL básico pode ser `http://127.0.0.1:8080/v1`. Quando o serviço é executado no Docker, “loopback” refere-se ao container, e não ao host físico. Use um endereço acessível a partir do espaço de rede do Controller. O registro de um Worker remoto sozinho não garante que sua API de inferência seja acessível.

O validador de URL do modelo exige HTTPS, exceto para casos em que o endereço é HTTP em hosts locais (`localhost`, `127.0.0.1`, `::1`). Um endpoint HTTP em um endereço LAN ou nome de serviço Docker deve ser acessível através de um gateway HTTPS. A opção de uso do endpoint privado do Hosted Chat não é aplicável. Os URLs básicos não devem conter credenciais embutidas, fragmentos ou strings de consulta.

Use o TLS para endpoints remotos. Restreia o acesso a gateways privados confiáveis. Verifique os identificadores dos modelos em comparação com o servidor de inferência. Nunca coloque chaves de API em prompts, capturas de tela, strings de consulta ou configurações publicadas. Deixe a chave da API em branco ao editar um canal existente, para preservar a chave salva; use conexão sem chave apenas quando o serviço permitir isso.

## Padrões configurados pelo ambiente

O perfil integrado do OpenAI pode ser configurado antes do lançamento, usando `LOCAL_SHELL_MCP_MODEL_BASE_URL` (ou `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL` e `LOCAL_SHELL_MCP_MODEL_API_KEY` (ou `OPENAI_API_KEY`). Os perfis integrados do Anthropic e Google podem ler `ANTHROPIC_API_KEY` e `GOOGLE_KEY`/`GOOGLE_API_KEY`, respectivamente. Os perfis integrados salvos têm prioridade sobre os padrões derivados do ambiente; use canais nomeados para vários endpoints independentes. Os padrões configurados pelo ambiente não são uma alternativa para proteger as senhas do serviço.

## Autorização do conta ChatGPT

O canal de controle/Codex utiliza um fluxo de autorização baseado em uma conta ChatGPT, em vez de uma chave API comum. O processo de autorização deve ser iniciado a partir da gestão do canal, e o login deve ser feito na página oficial de autorização. Em uma implantação local, o processo de callback pode ser concluído automaticamente. Se o navegador não conseguir se conectar ao listener de loopback, basta copiar o URL completo do campo de endereço e colá-lo na caixa de diálogo de autorização. É esperado que ocorra algum tipo de falha de conexão no endereço de loopback nesse fluxo manual.

Trate a URL de retorno como uma credencial: nunca a envie em uma conversa nem a publique. O Controller armazena a autorização no servidor e renova as credenciais quando possível. Autorize novamente a conta se ela expirar ou se o acesso for revogado. Os modelos disponíveis, os limites do plano e o uso permitido são determinados pelo serviço de conta de origem; o LSM não fornece cota adicional de assinatura.

## Descoberta de modelos e limites de contexto

Ative a descoberta automática para solicitar informações sobre o modelo do provedor. O Controller atualiza essas informações periodicamente (atualmente, a cada dez minutos); também é possível realizar atualizações manuais. Caso a descoberta falhe, os dados do modelo salvos anteriormente continuam salvos. Se o provedor não tiver um endereço de endpoint compatível para listar os modelos, desative a descoberta e insira manualmente os identificadores dos modelos, um por linha.

A descoberta reconhece metadados explícitos da janela de contexto, incluindo `limit.context` aninhado do OpenCode Go/Zen, `context_length` do OpenRouter, `max_model_len` do vLLM e `inputTokenLimit` do Gemini. Quando apenas o comprimento máximo de entrada é informado, ele é usado como alternativa; limites de saída e nomes de modelos não determinam a capacidade de contexto. Sem esses dois dados, a janela permanece desconhecida.

Especifique a janela de contexto para cada modelo, quando ela for conhecida. Um valor explícito por modelo substitui os metadados descobertos ou preenche valores faltantes. O editor aceita de 1 a 2.000.000 de tokens; isso é um intervalo de configuração, e não uma garantia de que o provedor suportará essa capacidade. Use o limite efetivo para sua implementação, levando em consideração as configurações do lado do servidor e os limites próprios do modelo.

## Amostragem, raciocínio e uso

Os valores padrão de canal/modelo controlam os parâmetros de solicitação suportados pelo provedor selecionado. O compositor de chat pode exibir informações sobre o processo de raciocínio, se disponível. Diferentes protocolos implementam a amostragem e o raciocínio de maneiras diferentes; uma opção pode não ser suportada por um determinado modelo. Comece com os valores padrão do provedor, e depois altere uma configuração de cada vez.

O LSM pode solicitar informações sobre o uso exato do token de streaming. No entanto, ele pode recorrer a outras opções quando o provedor rejeitar explicitamente essa opção de uso. Um endpoint que não retorna informações sobre o uso do token não pode fornecer dados precisos sobre a faturamento ou as estatísticas de cache. Para mais detalhes, consulte [Memória e contexto](context.md).

## Alterar e excluir canais

A conversa mantém seu modelo/Agent selecionado e sua história de conversas. É necessário mudar o modelo quando se alteram os endpoints ou quando se necessita depurar um problema relacionado ao provedor. O nome de um canal em uso é restrito, a fim de proteger as referências relacionadas a esse canal. A exclusão de um canal em uso requer confirmação adicional: a história da conversa permanece, mas os Agentes e os chats que fazem referência ao canal excluído devem selecionar um substituto adequado antes de continuar com a execução.

As configurações dos canais são do lado do servidor, e não são configurações pré-definidas apenas para o navegador. As credenciais não são retornadas nas respostas normais do catálogo de canais. É necessário proteger o diretório de estado do Controller e as cópias de segurança, pois esses dados contêm credenciais.

## Lista de verificação de conexão

1. Verifique se o Controller consegue acessar o host da API e se o TLS está configurado corretamente.
2. Verifique o caminho base, o protocolo, as credenciais e o ID exato do modelo.
3. Atualize as informações de descoberta ou insira manualmente um modelo conhecido.
4. Envie uma mensagem de texto simples, e então teste uma pequena chamada de ferramenta.
5. Verifique os detalhes dos erros, como status HTTP, tempo limite ou opções não suportadas. Não tente repetidamente inserir credenciais inválidas.

Para mais informações sobre como lidar com limites de taxa, interrupções de streaming e erros de autorização, consulte [Administração e solução de problemas](administration.md).
