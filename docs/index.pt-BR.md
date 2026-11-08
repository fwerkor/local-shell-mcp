<!-- i18n-source-sha256: f8fefdb11bbe7b5b755fd59ee829b2771e8c2e9694d5b9db40f8693f53c16960 -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">Espaço de trabalho de IA auto-hospedado · Plano de controle MCP</span>

# local-shell-mcp

Bate-papo, projetos, arquivos, terminais, máquinas remotas e ferramentas de IA em uma interface auto-hospedada. Conecte clientes MCP externos quando precisar deles.

<div class="hero-actions" markdown>
[Começar](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Referência de ferramentas](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Ambiente real de programação
Execute tests, inspecione repositories, aplique patches, opere Git e mantenha audit trail por um único MCP endpoint.
</div>

<div class="feature-card" markdown>
### Espaço de trabalho web unificado
Use o bate-papo integrado e o histórico do projeto junto com arquivos do Controlador, terminais, área de trabalho, sessões, controles remotos e auditoria. Os clientes MCP externos permanecem opcionais.
</div>

<div class="feature-card" markdown>
### Controle de máquinas remotas
Conecte máquinas atrás de NAT, firewall ou HPC por conexões worker de saída sem abrir portas SSH.
</div>
</div>

## O que oferece

`local-shell-mcp` fornece um espaço de trabalho de IA auto-hospedado unificado e um servidor MCP para clientes externos. Ele fornece shell, shell persistente, sistema de arquivos, pesquisa, patch, Git, Playwright, auditoria, sessões lógicas duráveis ​​com planos de metas opcionais, link de arquivo tokenizado e ferramentas de trabalho remoto por meio de endpoints MCP autenticados.

Use quando a IA precisa inspecionar repository, executar tests, editar arquivos, operar Git, coletar browser evidence, produzir downloadable artifacts ou controlar uma remote machine que só consegue conectar de saída ao control server.

## Arquitetura

```text
Camada runtime: Docker / VS Code extension / binary / Python / stdio
Camada de exposição: localhost / HTTPS proxy / tunnel / stdio pipe
Camada de cliente: WebUI/Gemini/ChatGPT/cliente MCP genérico unificado
Workspace controlado: /workspace or configured workspace root
Remote workers opcionais: outbound machine connections
```

O limite de isolamento pretendido é o container ou VM que executa o serviço.

## Começar por cenário

| Cenário | Comece aqui | Por quê |
|---|---|---|
| Espaço de trabalho do navegador principal | [Unified web workspace](getting-started/web-workspace.md) | Chat, projetos e páginas de controle LSM com login compartilhado |
| Implantação do primeiro controlador | [Quickstart](getting-started/quickstart.md) | Binário recomendado, OAuth e primeiro acesso no navegador |
| Escolher a camada runtime | [Runtime choices](guides/deployment.md) | Explica Docker, VS Code, binary, Python e stdio como opções de runtime separadas |
| Conectando Gemini Spark | [Gemini Custom Apps](getting-started/gemini-spark.md) | Elegibilidade, URL HTTPS MCP, OAuth e testes |
| Adicionar ChatGPT como client | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, primeiro prompt seguro, tool discovery |
| Adicionar LSM ao DeepSeek Harness | [Plugin DeepSeek Harness](clients/deepseek-harness.md) | Instalar este repository como bundle DSH mantendo toda a superfície de ferramentas LSM e remote workers |
| Executar pelo VS Code | [VS Code extension runtime](installation/vscode-extension.md) | Runtime iniciado pelo editor e notas de segurança do host |
| Aprender a operar o toolset | [Usage patterns](guides/usage-patterns.md) | Templates de prompt e orientação de escolha de tools |
| Entender cada tool | [Tools reference](reference/tools.md) | Purpose, inputs, returns, combinations e notes de cada tool |
| Conectar HPC, NPU/GPU ou server node | [Remote workers](guides/remote-workers.md) | Outbound worker join flow e remote tool usage |
| Compartilhar arquivos gerados | [File links](guides/file-links.md) | URLs tokenizadas com TTL e revogação |
| Endurecer o deployment | [Security](security.md) | Isolamento, OAuth, workspace scope e audit logs |

## Principais famílias de tools

| Família | Exemplos | Uso |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, tests, scripts e processos longos |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Inspeção de repository e edits precisos |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Workflows de controle de versão revisáveis |
| Sessions e goals | `session_manage`, `plan_manage` | Handoff durável de tarefas, relatórios de progresso e Goal mode opcional |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Interação persistente, UI checks, screenshots, docs renderizados e texto de página |
| File links | `link_create`, `link_revoke` | Baixar artefatos gerados pelo chat |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | Máquinas atrás de NAT, firewalls ou fluxos de login de cluster |

## Workflows típicos

### Codificação no espaço de trabalho da web

1. Inicie um controlador LSM e o [unified web workspace](getting-started/web-workspace.md) opcional.
2. Abra `/ui` e faça login usando a identidade LSM.
3. Configure um endpoint modelo e abra uma nova conversa.
4. Peça ao modelo para inspecionar o repositório e executar verificações somente leitura primeiro.
5. Depois permita patch files, tests, diff review, commit e push quando aprovados.
6. Revise audit log quando o task envolver file links ou remote systems.

### Host HPC ou accelerator remoto

1. Crie um remote worker invite de uso único.
2. Cole o command gerado no remote host.
3. Use tools normais com `machine`; Git via `run_shell` e transfer via `remote_transfer`.
4. Revogue o worker após o task.

### Geração de artefatos

1. Deixe a IA gerar um file em `/workspace`.
2. Crie tokenized file link com TTL/download limits.
3. Compartilhe o link no chat.
4. Revogue quando terminar.

## Idioma

Este site é construído com o plugin i18n nativo do MkDocs. Use o seletor de idioma no header para alternar entre English e páginas traduzidas. Páginas sem tradução fazem fallback para English.
