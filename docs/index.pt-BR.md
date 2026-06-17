# Documentação do local-shell-mcp

Um plano de controle local para ChatGPT Developer Mode e outros clientes MCP. Ele expõe um workspace controlado, shell, arquivos, Git, automação do navegador, links de arquivos e workers remotos como ferramentas MCP.

## Caminhos da documentação

- [Início rápido](getting-started/quickstart.md)
- [Conector ChatGPT](getting-started/chatgpt-connector.md)
- [Workers remotos](guides/remote-workers.md)
- [Segurança](security.md)
- [Solução de problemas](troubleshooting.md)

## Arquitetura principal

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Regra de segurança essencial

Em implantações públicas, habilite OAuth e não monte o Docker socket, a raiz do host nem credenciais de longa duração.
