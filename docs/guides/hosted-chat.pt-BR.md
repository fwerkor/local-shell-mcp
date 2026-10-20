<!-- i18n-source-sha256: f2dd1c4fffcc9783c739a12868fbcfa0023e0e3a783c8ba929f84107e3959e9a -->
# Bate-papo hospedado (opcional)

O Hosted Chat é um cliente de bate-papo BYOK e aplicativos MCP auto-hospedado integrado à interface humana do LSM. **não** é um modo de Sessão Lógica: as conversas têm identidades independentes e podem opcionalmente anexar uma Sessão Lógica LSM existente. ChatGPT e outros clientes externos continuam trabalhando com as mesmas sessões e ferramentas LSM.

## Habilitar

O bate-papo hospedado está desabilitado por padrão. Definir:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Reinicie o controlador e abra **Hosted Chat** imediatamente abaixo do seletor Web UI/TUI. O recurso também possui uma entrada na barra superior móvel. O host do chat usa a identidade e os escopos LSM OAuth existentes. O mesmo controlador opera o servidor MCP usado pelo loop de ferramentas do modelo; Os trabalhadores não podem iniciar a execução.

## Perfis de modelo

Escolha **Perfis de modelo** para criar/editar um perfil com um nome, URL base da API HTTPS compatível com OpenAI, ID do modelo e chave de API opcional. Vários perfis podem coexistir e as conversas podem mudar de modelo.

Perfis, conversas, histórico completo de mensagens e resultados de chamadas de ferramentas são **salvos no servidor** por meio do back-end de estado LSM configurado. Seu escopo está vinculado ao principal autenticado. A chave de API é criptografada com AES-GCM e nunca é retornada de endpoints de lista de perfis ou detalhes de perfil. Ele não é armazenado no armazenamento do navegador, enviado ao modelo como um prompt ou incluído nos logs de auditoria. O host do chat passa apenas para a API do modelo escolhido.

A primeira implantação baseada em arquivo cria `hosted-chat-encryption-key` no diretório de estado com modo 0600. **Faça backup deste arquivo junto com os dados de estado. Sem ele, as chaves de API salvas não podem ser descriptografadas.** Se o controlador usar Redis, várias réplicas ou outro back-end de estado que não seja de arquivo, configure uma chave URL-safe-base64 estável e compartilhada de 32 bytes:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

Não altere esta configuração sem migrar os perfis criptografados. Não use armazenamento de estado na memória quando forem necessárias conversas duráveis.

Por padrão, somente terminais de modelo HTTPS com nomes de host DNS são aceitos; endpoints locais/privados e HTTP são recusados ​​para reduzir o risco de falsificação de solicitação do lado do servidor. Os administradores que hospedam deliberadamente um gateway de modelo privado confiável podem optar por:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

Não habilite isso em um controlador multiusuário não confiável, a menos que os usuários estejam autorizados a entrar em contato com serviços internos.

## Conversas e aplicativos MCP

Crie uma conversa usando um perfil de modelo salvo. Cada turno enviado torna-se uma tarefa em segundo plano de propriedade do servidor; fechar o navegador não cancela a tarefa. O texto concluído e as chamadas de ferramentas são verificados de forma duradoura entre as etapas do modelo/ferramenta. Pare explicitamente para interromper. Na reinicialização do controlador, as execuções interrompidas são marcadas como tal e podem ser continuadas em um novo turno, mas **as chamadas de ferramenta com resultado desconhecido nunca são reproduzidas automaticamente**.

Todo o histórico de mensagens da conversa é mantido no armazenamento. Apenas uma janela recente limitada é enviada ao modelo de uma só vez para controlar o tamanho do contexto. As chamadas de ferramenta são enviadas através do endpoint MCP autenticado do LSM, preservando todas as permissões comuns da ferramenta e comportamento de auditoria/preflight.

Abra o **Live Workspace** para renderizar o recurso `workspace_open` MCP Apps existente do LSM dentro de uma visualização incorporada. O host usa a ponte `@modelcontextprotocol/ext-apps` para ciclo de vida do aplicativo, renovação de credenciais, chamadas de ferramentas e ações entre humanos e agentes. Nenhum segundo gerenciador de arquivos, terminal, auditoria ou UI de trabalho é implementado.

O `session_id` opcional anexado permite que o Hosted Chat use e exiba uma sessão lógica existente; ele não reclassifica a Sessão nem concede ao Hosted Chat a propriedade dela. Os identificadores de conversa de bate-papo e os identificadores de sessão lógica são separados.

## Limites

- As solicitações de modelo usam conclusões de bate-papo compatíveis com OpenAI com chamada de ferramenta; outros protocolos de provedor requerem um adaptador.
- As proteções por turno limitam as iterações do modelo e as chamadas de ferramentas. Tarefas mais longas podem ser continuadas num novo turno usando o histórico durável.
- A exclusão da conversa de bate-papo é explícita. Nenhuma remoção automática de histórico é executada.
- O Controlador deve ser acessível pela rede por seu próprio cliente MCP e o navegador deve ser autorizado para a API LSM Live Workspace.
