<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# Conectividade de rede

MCP client HTTP fora da máquina precisam de um HTTPS origin acessível. Esta página trata do roteamento de rede, não da escolha do runtime.

O client endpoint normalmente termina em `/mcp`:

```text
https://your-public-host.example.com/mcp
```

A configuração public base URL do servidor contém apenas o origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Não inclua `/mcp` nessa base URL.

## Opções de conectividade

**Recomendado:** Para acesso público, implante em um servidor público ou encaminhe o tráfego por um servidor público com proxy reverso HTTPS.

**Não recomendado:** O upload do lado do cliente via Cloudflare Tunnel pode ser muito lento, dificultando o envio e a transferência de arquivos. Use apenas se não houver opção de implantação ou encaminhamento por servidor público.


| Opção | Quando usar |
|---|---|
| Caddy | TLS automático simples |
| Nginx ou Nginx Proxy Manager | Infraestrutura Nginx existente |
| Traefik | Roteamento container-native existente |
| Encaminhamento por servidor público | Para acesso público, implante em um servidor público ou encaminhe o tráfego por um servidor público com proxy reverso HTTPS. |
| Cloudflare Tunnel (não recomendado) | Encaminhe por servidor público; Cloudflare Tunnel apenas como último recurso |

## Caminhos

Encaminhe todo o origin para o servidor em execução. Caminhos importantes incluem:

| Caminho | Finalidade |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Verificações de integridade |
| `/.well-known/...` | Metadados de descoberta do client |
| `/oauth/...` | Fluxo de autorização do client |
| `/downloads/...` | Links opcionais de arquivos gerados |
| `/join/...`, `/remote/...` | Fluxo opcional de remote-worker |

## Comportamento do proxy

O proxy deve preservar os caminhos, encaminhar request bodies, suportar responses longas e evitar timeouts muito curtos.

## Verificações

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Erros comuns

| Erro | Correção |
|---|---|
| Usar `https://host` no ChatGPT em vez de `https://host/mcp` | Adicionar `/mcp` apenas ao client endpoint |
| Definir `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | Definir somente o origin |
| Rotear apenas `/mcp` | Rotear todo o origin para que discovery e autorização também funcionem |
| Executar host runtime com workspace amplo | Usar workspace restrito ou Docker |

## Combinação sugerida

| Runtime | Padrão de rede |
|---|---|
| Docker Compose em servidor | Proxy reverso HTTPS |
| Docker Compose em máquina doméstica | Encaminhe por servidor público; Cloudflare Tunnel apenas como último recurso |
| VS Code extension em notebook | Encaminhamento por servidor público |
| Binary em VM | Reverse proxy na VM ou na borda da rede |
| Servidor de desenvolvimento Python/source | Normalmente apenas localhost |
| Stdio mode | Sem caminho HTTP; usar MCP client local |
