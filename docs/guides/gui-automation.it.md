<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# Automazione della GUI desktop

`local-shell-mcp` può osservare e controllare applicazioni desktop native su Linux, Windows e macOS. L'interfaccia pubblica resta volutamente ridotta:

| Strumento | Scopo |
|---|---|
| `gui_list` | Elenca le finestre delle applicazioni visibili e riporta il backend nativo e le capacità attive. |
| `gui_state` | Osserva una finestra. Restituisce uno `state_id` a breve durata, elementi di accessibilità, geometria della finestra e, facoltativamente, uno screenshot MCP nativo. |
| `gui_action` | Esegue azioni semantiche o basate su coordinate esattamente sull'osservazione indicata. |

Tutti e tre gli strumenti accettano il parametro opzionale `machine`, quindi lo stesso flusso può operare su un worker desktop connesso.

## Osservare, poi agire

Inizia con `gui_list`, seleziona un `window_id` e poi chiama `gui_state`. Quando il controllo di destinazione dispone di un elemento di accessibilità, preferisci l'`element_id` restituito:

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

Usa coordinate `x`/`y` relative alla finestra solo quando l'interfaccia non espone un elemento di accessibilità utile, ad esempio una canvas o un controllo disegnato su misura. I limiti degli elementi e gli screenshot restituiti usano lo stesso spazio di pixel logici relativo alla finestra, anche su desktop HiDPI/Retina. Le coordinate grezze esterne alla finestra selezionata vengono rifiutate.

Uno `state_id` scade dopo 30 secondi ed è monouso. Le azioni a coordinate verificano inoltre che la finestra non sia stata spostata o ridimensionata dopo l'osservazione. Se uno di questi controlli fallisce, richiama `gui_state` invece di riutilizzare coordinate obsolete.

Le azioni supportate sono `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus` e `wait`.

## Controllo umano nella Native WebUI

La Native WebUI include una pagina **Desktop** per controllare direttamente gli stessi backend GUI nativi. Scegli una macchina e una finestra, quindi interagisci con l'immagine della finestra tramite clic, doppio clic, clic destro, trascinamento, rotellina, scorciatoie da tastiera o il campo di testo per input IME/CJK.

Questo percorso è volutamente separato dalla semantica di `state_id` usata dal modello. Ogni frame visualizzato include la geometria osservata della finestra; ogni richiesta di input umano verifica che la finestra conservi esattamente quella geometria prima di iniettare l'input. Se la finestra è stata spostata, ridimensionata o è scomparsa, l'azione viene rifiutata e la WebUI aggiorna l'osservazione. Le coordinate grezze restano limitate alla finestra selezionata.

Le azioni di tastiera e testo mettono esplicitamente a fuoco la finestra nativa selezionata prima dell'iniezione. La WebUI usa un polling leggero di screenshot invece di streaming video VNC/WebRTC; l'RPC remoto `gui_human_action` è un'operazione interna controller-worker e non uno strumento MCP esposto ai modelli.

## Backend nativi

| Piattaforma | Accessibilità / controllo semantico | Cattura e input grezzo |
|---|---|---|
| Windows | Microsoft UI Automation | Cattura della finestra e input nativo Windows per mouse e tastiera |
| macOS | Accessibility (`AXUIElement`) | `screencapture` per la finestra selezionata e input Quartz `CGEvent` |
| Linux | AT-SPI | Input/cattura nativi X11; Wayland usa cattura desktop nativa e XDG Desktop Portal RemoteDesktop/ScreenCast per l'input grezzo |

Quando possibile vengono tentate prima le azioni semantiche. Un pulsante con un'azione nativa di invoke/press può quindi essere attivato senza stimare una coordinata. Le coordinate visive restano il fallback per contenuti non accessibili o disegnati su misura.

## Configurazione della piattaforma

### Windows

Esegui LSM nella stessa sessione desktop interattiva delle applicazioni da controllare. L'installazione base di `local-shell-mcp` resta sicura in ambiente headless e non richiede l'adapter Windows UI Automation; installa l'extra opzionale `local-shell-mcp[gui]` quando serve il controllo GUI locale su Windows.

### macOS

Concedi al processo host di LSM:

- Permesso **Accessibilità** per controllo semantico e input.
- Permesso **Registrazione schermo** per gli screenshot.

Il pacchetto base non richiede PyObjC. Installa l'extra opzionale `local-shell-mcp[gui]` quando serve il controllo GUI locale su macOS; le macchine che non usano strumenti GUI non hanno bisogno di questi framework.

### Linux

La sessione desktop deve esporre AT-SPI. Nei sistemi Debian/Ubuntu i binding di sistema richiesti sono normalmente disponibili con:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

Il pacchetto base non richiede gli adapter Python X11 o D-Bus. L'extra opzionale `local-shell-mcp[gui]` li installa per l'uso GUI locale. I worker remoti rilevano la sessione Linux attiva prima di qualsiasi bootstrap delle dipendenze GUI: X11 richiede solo l'adapter X11, Wayland solo l'adapter D-Bus e i worker headless non installano nessuno dei due. Su Wayland il fallback per puntatore/tastiera usa l'API XDG Desktop Portal RemoteDesktop, quindi il desktop può mostrare una selezione iniziale di permesso/sessione. Sono supportate le implementazioni portal di KDE e GNOME. Gli screenshot della finestra usano il percorso di cattura nativo disponibile e, quando necessario, il portale Screenshot.

I worker LSM spesso partono fuori dall'ambiente di login grafico. Il backend Linux recupera `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE` e le variabili correlate dall'ambiente systemd dell'utente quando non vengono ereditate direttamente.

## Desktop remoti

Gli strumenti GUI vengono eseguiti sulla macchina selezionata, non sul controller. Il worker remoto deve appartenere all'utente/sessione proprietario del desktop di destinazione. Gli adapter GUI sono caricati in modo lazy e limitati alle chiamate GUI: l'avvio normale del worker e l'uso di shell/file/browser non li installano né importano. Su Linux, un worker headless restituisce GUI non disponibile prima di qualsiasi bootstrap pip GUI; un worker grafico verifica o installa solo l'adapter richiesto dalla sessione X11 o Wayland attiva.

Gli screenshot restituiti da un `gui_state` remoto vengono trasferiti tramite il percorso di trasferimento file di LSM ed esposti al modello come contenuto immagine MCP nativo; non vengono incorporati nella risposta JSON del worker.
