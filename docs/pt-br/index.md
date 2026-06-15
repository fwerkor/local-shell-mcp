# Documentação do local-shell-mcp

Um plano de controle local para ChatGPT Developer Mode e outros clientes MCP. Expõe workspace controlado, shell, arquivos, Git, automação de navegador, links de arquivos e workers remotos como ferramentas MCP.

## Documentation paths

- [Início rápido](getting-started/quickstart.md)
- [Conector ChatGPT](getting-started/chatgpt-connector.md)
- [Workers remotos](guides/remote-workers.md)
- [Segurança](security.md)
- [Solução de problemas](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

Em implantações públicas, habilite OAuth e não monte o Docker socket, a raiz do host ou credenciais duradouras.
