# Configuração

Esta página descreve o cenário “Configuração” e mantém a estrutura Runtime/Client comum do site.

## Visão geral

Runtime define como o processo do servidor é executado e qual workspace ele controla. Client define como ChatGPT ou outro cliente MCP se conecta. Docker, extensão do VS Code, binários independentes, instalações por Python/pipx/código-fonte e stdio são opções de Runtime; conector ChatGPT, cliente MCP HTTP genérico e cliente MCP stdio são conexões Client.

## Quando usar

- Use esta página quando o caminho de Runtime ou Client escolhido corresponder ao título.
- Mantenha consistentes a raiz do workspace, a base URL pública, o MCP endpoint, o modo de autenticação e as ferramentas disponíveis no host.
- Para ChatGPT web/app, exponha um MCP endpoint HTTPS terminado em `/mcp`.
- Para clientes MCP locais, use HTTP localhost ou `local-shell-mcp --mode stdio` conforme o suporte do cliente.

## Passos

1. Escolha primeiro a página de instalação do Runtime.
2. Inicie o Runtime e verifique `/healthz` quando usar o modo HTTP.
3. Depois escolha a página de conexão do Client.
4. Registre o MCP endpoint ou o comando stdio no Client.
5. Chame `environment_info` para verificar o workspace e as configurações efetivas.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Verificação

- `environment_info` confirma configurações do Runtime e workspace.
- `tree_view` confirma arquivos visíveis.
- `run_shell_tool` confirma o ambiente de comandos.

## Notas

Prefira etapas pequenas e verificáveis: inspecionar, editar, ver o diff, testar, escanear e fazer commit. Tarefas grandes também devem ser divididas em chamadas de ferramentas auditáveis.
