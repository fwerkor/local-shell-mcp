<!-- i18n-source-sha256: 474398c2065f510156f7fba24967ca8f6600b586ffb1e002416b7a10dc34c3dc -->
# Espaço de trabalho web unificado

O **espaço de trabalho web LSM unificado** é a maneira recomendada de usar local-shell-mcp no dia a dia. Ele combina chat de IA, histórico de projeto e plano de controle LSM em uma interface responsiva, baseada em um frontend LibreChat modificado e vendido. Ainda é possível conectar clientes MCP externos, como [ChatGPT](chatgpt-connector.md) ou [Gemini](gemini-spark.md).

O espaço de trabalho é **auto-hospedado e de instalação opcional**: é um serviço da Web separado, não faz parte da imagem mínima do controlador, do executável independente ou do pacote de trabalho remoto. As implantações somente de controlador mantêm a IU original do navegador e o OpenTUI.

## O que há no espaço de trabalho?

| Área | O que você pode fazer |
|---|---|
| Bate-papo e projetos | Escolha um modelo configurado, crie conversas, organize projetos, encontre chats anteriores e arquive conversas. O histórico permanece no servidor. |
| Visão geral do controlador | Veja a integridade, atividades recentes e máquinas conectadas. |
| Arquivos | Navegue e gerencie arquivos locais ou remotos. |
| Terminais | Trabalhe com terminais persistentes no Controlador ou nos Trabalhadores. |
| Área de trabalho | Inspecione e controle sessões remotas da GUI. |
| Sessões | Inspecione tarefas LSM duráveis e seu ciclo de vida. |
| Controles remotos | Conecte e administre trabalhadores de saída. |
| Auditoria | Inspecione a atividade da ferramenta originada no modelo. |
| MCP aninhado | Registre, edite, habilite, desabilite, atualize e remova servidores MCP externos atrás do LSM. |

As rotas do Controlador são `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` e `/control/audit`. O bate-papo abre em `/c/new`. O gerenciador LSM MCP controla **o registro MCP aninhado do LSM**; não cria um segundo registro no LibreChat.

## Implante a pilha de chat opcional

1. [Install and start an LSM Controller](quickstart.md) com OAuth, um espaço de trabalho adequadamente isolado e armazenamento de estado persistente `file` ou `redis`. Instale o Docker Compose e clone o repositório no host que executa a pilha da web.
2. Forneça **duas origens HTTPS no mesmo site**, como `https://lsm.example.org` para Controller e `https://chat.example.org` para o espaço de trabalho. O serviço de chat não é exposto diretamente em uma rede não confiável.
3. Gere um segredo de ponte com `openssl rand -hex 32`. Configure essas variáveis ​​de ambiente no **serviço Controller** usando esse segredo e reinicie-o:

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. Na finalização da compra do repositório, configure a pilha da web opcional. Use um arquivo de ambiente privado ou exporte os valores mostrados abaixo; gere segredos fortes e únicos e não os cometa:

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Renderize a configuração privada e, em seguida, crie e inicie a pilha de chat implantada separadamente:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

Ao usar a implantação raiz do Docker Compose, as variáveis ​​do controlador acima pertencem à raiz `.env` e são encaminhadas para o contêiner. Os valores do serviço de chat podem ser fornecidos por meio de exportações de shell ou de um arquivo de ambiente privado. O contêiner Controller deve ser acessível a partir do contêiner de bate-papo em `http://local-shell-mcp:8765` na rede Docker nomeada. Porta proxy reverso `127.0.0.1:3080` para a origem HTTPS do chat, preserve o host externo e siga o [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) no repositório. A pilha da web executa Node.js, MongoDB, Meilisearch e SearXNG; eles **não** estão incluídos em Trabalhadores. Esta implementação separada não é iniciada por um `docker compose up -d` simples na raiz do repositório.

## Faça login e use o bate-papo

1. Abra `https://lsm.example.org/ui`, autentique usando o login do **LSM Controller** e siga a transferência única para o espaço de trabalho da web. Você não cria uma segunda conta de usuário LibreChat.
2. Configure um provedor LLM ou terminal modelo disponível para o serviço de chat. A área de trabalho fornece a interface de chat e a ponte de ferramentas; **não inclui modelo ou créditos de API**.
3. Crie uma conversa. As ferramentas de pesquisa na Web e LSM são habilitadas por padrão, sujeitas às permissões do Controlador. Use os controles **Web**, **LSM**, **MCP externo** e **Memória** por conversa conforme necessário.
4. Comece com uma solicitação somente leitura: "Verifique o status do controlador e liste a raiz do espaço de trabalho. Não modifique os arquivos".
5. Navegue até **Arquivos**, **Terminais**, **Desktop**, **Sessões**, **Remotos** ou **Auditoria** para inspeção e controle diretos.

Os uploads de chat (até 32 MiB) são armazenados no espaço de trabalho do Controlador e seus caminhos absolutos são fornecidos ao modelo. Os uploads do navegador não concedem permissões adicionais de arquivo. As chamadas de ferramentas voltadas para o modelo passam pela autorização do LSM, pela auditoria e pelo roteador do trabalhador remoto.

## MCP externo, segurança e dados

Use a barra lateral do espaço de trabalho MCP para gerenciar servidores MCP externos aninhados. Isso oferece suporte a servidores stdio locais e servidores HTTP, incluindo variáveis ​​de ambiente privadas separadas e cabeçalhos de solicitação. Os segredos não são retornados ao navegador. A alternância de bate-papo **MCP externo** permite pesquisa, inspeção e invocação de ferramentas aninhadas; ele não concede o modelo `mcp_manage` quando as ferramentas LSM nativas estão desativadas. O gerenciamento da UI é protegido pela autorização normal do Controlador.

Mensagens de bate-papo, projetos e arquivos são armazenados no lado do servidor no MongoDB da pilha da web; a pesquisa usa Meilisearch. O Controlador possui separadamente permissões de ferramentas, identidades de trabalhadores, estado de sessão e auditoria. Faça backup de ambos os armazenamentos de dados se precisar reter todo o histórico. O backend do chat é de usuário único com login do LSM; não exponha sua API interna ou bancos de dados ao público.

A UI é um aplicativo de nível superior, **não um iframe**. Se o serviço de chat opcional não estiver configurado, `/ui` continuará a servir o WebUI do LSM original. OpenTUI nativo e clientes externos permanecem com suporte.

## Solução de problemas

- **O redirecionamento permanece na IU original:** verifique `LOCAL_SHELL_MCP_LIBRECHAT_URL`, um back-end de estado do controlador persistente e o proxy reverso HTTPS da pilha da web.
- **Falha no login ou transferência:** verifique exatamente o mesmo segredo de ponte de 32 bytes ou mais em ambos os lados, correspondendo às origens do mesmo site, HTTPS e relógios do servidor.
- **O chat é carregado, mas não pode responder:** configure um endpoint de modelo real ou uma credencial de API e verifique os logs do contêiner de chat.
- **Faltam ferramentas MCP:** verifique os escopos do controlador e as alternâncias por conversa; o registro do servidor aninhado é separado do banco de dados LibreChat MCP.
- **Arquivos ou sessões aparecem vazios:** verifique se o chat chega ao controlador e ao espaço de trabalho corretos e inspecione seus logs de autenticação de API.

Para obter detalhes e atualizações de implementação, consulte [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) e [human interface guide](../guides/human-interface.md).
