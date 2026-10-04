<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# Automação de GUI de desktop

`local-shell-mcp` pode observar e controlar aplicativos nativos de desktop no Linux, Windows e macOS. A superfície pública é mantida intencionalmente pequena:

| Ferramenta | Finalidade |
|---|---|
| `gui_list` | Lista janelas visíveis de aplicativos e informa o backend nativo ativo e suas capacidades. |
| `gui_state` | Observa uma janela. Retorna um `state_id` de curta duração, elementos de acessibilidade, geometria da janela e, opcionalmente, uma captura de tela MCP nativa. |
| `gui_action` | Executa ações semânticas ou por coordenadas exatamente contra essa observação. |

As três ferramentas aceitam o parâmetro opcional `machine`, portanto o mesmo fluxo pode operar em um worker desktop conectado.

## Observe e depois aja

Comece com `gui_list`, escolha um `window_id` e então chame `gui_state`. Prefira o `element_id` de acessibilidade retornado sempre que ele representar o controle de destino:

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Use coordenadas `x`/`y` relativas à janela somente quando a interface não tiver um elemento de acessibilidade útil, como um canvas ou controle desenhado de forma personalizada. Os limites dos elementos e as capturas usam o mesmo espaço de pixels lógicos relativo à janela, inclusive em desktops HiDPI/Retina. Coordenadas brutas fora da janela selecionada são rejeitadas.

Um `state_id` expira após 30 segundos e só pode ser usado uma vez. Ações por coordenadas também verificam se a janela alvo não foi movida ou redimensionada desde a observação. Se qualquer verificação falhar, chame `gui_state` novamente em vez de reutilizar coordenadas antigas.

As ações compatíveis são `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus` e `wait`.

## Controle humano na Native WebUI

A Native WebUI possui uma página **Desktop** para controle humano direto dos mesmos backends GUI nativos. Escolha uma máquina e uma janela e interaja com a imagem da janela usando clique, clique duplo, botão direito, arrastar, roda do mouse, atalhos de teclado ou o campo de texto para entrada IME/CJK.

Esse caminho é deliberadamente separado da semântica de `state_id` usada pelo modelo. Cada frame exibido leva a geometria observada da janela; toda solicitação de entrada humana valida que a janela ainda tem exatamente essa geometria antes de injetar a entrada. Se a janela foi movida, redimensionada ou desapareceu, a ação é rejeitada e a WebUI atualiza a observação. Coordenadas brutas continuam limitadas à janela selecionada.

Ações de teclado e texto colocam explicitamente o foco na janela nativa selecionada antes da injeção. A WebUI usa polling leve de capturas de tela em vez de streaming de vídeo VNC/WebRTC; o RPC remoto `gui_human_action` é uma operação interna controller-worker, não uma ferramenta MCP exposta aos modelos.

## Backends nativos

| Plataforma | Acessibilidade / controle semântico | Captura e entrada bruta |
|---|---|---|
| Windows | Microsoft UI Automation | Captura da janela e entrada nativa de mouse e teclado do Windows |
| macOS | Accessibility (`AXUIElement`) | `screencapture` da janela selecionada e entrada Quartz `CGEvent` |
| Linux | AT-SPI | Entrada/captura nativas X11; Wayland usa captura nativa do desktop e XDG Desktop Portal RemoteDesktop/ScreenCast |

Ações semânticas são tentadas primeiro quando possível. Assim, um botão com ação nativa invoke/press pode ser ativado sem adivinhar coordenadas de pixel. Coordenadas visuais permanecem como fallback para conteúdo inacessível ou desenhado de forma personalizada.

## Configuração da plataforma

### Windows

Execute o LSM na mesma sessão de desktop interativa dos aplicativos que ele deve controlar. A instalação base do `local-shell-mcp` continua segura em modo headless e não exige o adaptador Windows UI Automation; instale o extra opcional `local-shell-mcp[gui]` quando o controle GUI local do Windows for necessário.

### macOS

Conceda ao processo host do LSM:

- permissão de **Acessibilidade** para controle semântico e entrada;
- permissão de **Gravação da Tela** para capturas.

O pacote base não exige PyObjC. Instale o extra opcional `local-shell-mcp[gui]` quando precisar de controle GUI local no macOS; máquinas que nunca usam ferramentas GUI não precisam desses frameworks.

### Linux

A sessão de desktop deve expor AT-SPI. Em Debian/Ubuntu, os bindings de sistema necessários normalmente podem ser instalados com:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

O pacote base não exige os adaptadores Python X11 ou D-Bus. O extra opcional `local-shell-mcp[gui]` os instala para uso GUI local. Workers remotos detectam a sessão Linux ativa antes de qualquer bootstrap de dependência GUI: X11 precisa apenas do adaptador X11, Wayland apenas do adaptador D-Bus e workers headless não instalam nenhum dos dois. No Wayland, o fallback de ponteiro/teclado bruto usa a API XDG Desktop Portal RemoteDesktop, portanto o desktop pode exibir um seletor de permissão/sessão uma única vez. As implementações de portal do KDE e GNOME são compatíveis. Capturas da janela usam o caminho nativo disponível e recorrem ao portal Screenshot quando necessário.

Workers LSM frequentemente iniciam fora do ambiente de login gráfico. O backend Linux recupera `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE` e variáveis relacionadas do ambiente systemd do usuário quando elas não são herdadas diretamente.

## Desktops remotos

As ferramentas GUI são executadas na máquina selecionada, não no controller. O worker remoto deve pertencer ao usuário/sessão dono do desktop alvo. Adaptadores GUI são carregados de forma lazy e limitados a chamadas GUI: a inicialização normal do worker e o uso de shell/files/browser não os instalam nem importam. No Linux, um worker headless retorna GUI indisponível antes de qualquer bootstrap pip GUI; um worker gráfico verifica ou instala apenas o adaptador exigido pela sessão X11 ou Wayland ativa.

As capturas retornadas por um `gui_state` remoto são transferidas pelo caminho de transferência de arquivos do LSM e expostas ao modelo como conteúdo de imagem MCP nativo; elas não são incorporadas à resposta JSON do worker.
