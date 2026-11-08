<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
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

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## Faça login e use o bate-papo

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Os uploads de chat (até 32 MiB) são armazenados no espaço de trabalho do Controlador e seus caminhos absolutos são fornecidos ao modelo. Os uploads do navegador não concedem permissões adicionais de arquivo. As chamadas de ferramentas voltadas para o modelo passam pela autorização do LSM, pela auditoria e pelo roteador do trabalhador remoto.

## MCP externo, segurança e dados

Use a barra lateral do espaço de trabalho MCP para gerenciar servidores MCP externos aninhados. Isso oferece suporte a servidores stdio locais e servidores HTTP, incluindo variáveis ​​de ambiente privadas separadas e cabeçalhos de solicitação. Os segredos não são retornados ao navegador. A alternância de bate-papo **MCP externo** permite pesquisa, inspeção e invocação de ferramentas aninhadas; ele não concede o modelo `mcp_manage` quando as ferramentas LSM nativas estão desativadas. O gerenciamento da UI é protegido pela autorização normal do Controlador.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Solução de problemas

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Para obter detalhes e atualizações de implementação, consulte [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) e [human interface guide](../guides/human-interface.md).
