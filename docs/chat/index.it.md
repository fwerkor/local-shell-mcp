<!-- i18n-source-sha256: 8ec601aa8e9c57afef769d8346567626355ccf88e122e3296735b7af3639c562 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# WebUI Chat

LSM WebUI Chat è uno spazio di lavoro per agenti AI, gestito internamente dal Controller stesso. È possibile utilizzare il proprio endpoint di modello o un account supportato, e dare al modello l’accesso alle proprie tool e macchine. Non è necessario utilizzare alcun client esterno per farlo funzionare. Gli client esterni possono comunque connettersi allo stesso Controller in modo indipendente.

## Come i vari elementi si incastrano tra loro

- **Controller:** Il servizio Python che ospita l’applicazione web, gestisce le richieste dei utenti, esegue i comandi necessari per l’esecuzione delle operazioni, pianifica le attività da svolgere e mantiene lo stato persistente delle informazioni.
- **Canale di comunicazione**: si riferisce a una connessione tramite un’API specifica, oppure all’autorizzazione di un account supportato. Questo tipo di canale prevede le proprie credenziali, il protocollo utilizzato, l’elenco dei modelli disponibili e le impostazioni relative a tali modelli.
- **Modello:** Un identificatore utilizzato per riconoscere un modello all’interno di un canale. Lo stesso identificatore utilizzato su due canali non implica necessariamente lo stesso endpoint.
- **Agent**: Una configurazione riutilizzabile che combina un modello, istruzioni, strumenti, competenze e permessi.
- **Conversazione:** messaggi salvati, impostazioni, cronologia delle operazioni eseguite, e relazioni tra il modello/Agente utilizzato.
- **Progetto:** Un insieme di conversazioni con parametri predefiniti comuni tra tutti i partecipanti.
- **Worker:** Un bersaglio di esecuzione connesso all’esterno. Non si tratta di un fornitore di modelli o di un server di chat separato.
- **Sesiologia logica**: è un identificatore della task sull’ambiente di lavoro, distinto dall’ID della conversazione stessa. Un chat può utilizzare questo identificatore per tracciare i progressi e le attività svolte all’interno dell’ambiente di lavoro.

L’API di modello riceve come input il contesto visibile al modello, nonché i risultati ottenuti dagli strumenti utilizzati. Il controller esegue le operazioni autorizzate; il modello, invece, non si connette direttamente a un “Worker” né ottiene la chiave API del modello stesso. Il browser è responsabile della visualizzazione della conversazione e del controllo sul controller.

## Scegli un guida.

| Voglio… | Leggi |
|---|---|
| Installare, accedere e eseguire una prima operazione. | [Guida iniziale](../getting-started/web-workspace.md) |
| Connettere un’API o un account per l’utilizzo dei servizi. | [Canali e modelli](channels.md) |
| Creare agenti riutilizzabili e delegare compiti. | [Agenti e abilità](agents.md) |
| Gestire chat, file e progetti. | [Conversazioni](conversations.md) |
| Comprendere il funzionamento della memorizzazione delle informazioni e dei budget legati alle conversazioni. | [Memoria e contesto](context.md) |
| Restringere l’esecuzione e gestire gli strumenti MCP | [Strumenti e permessi](permissions.md) |
| Eseguire compiti e programmi di lunga durata. | [Obiettivi e automazione](automation.md) |
| Ricerca sul web e lettura di documenti. | [Ricerca in rete](../guides/webui-network-search.md) |
| Gestione, backup e debug delle implementazioni. | [Amministrazione e risoluzione dei problemi](administration.md) |

## Principi fondamentali.

Iniziare con una richiesta di tipo “leggero”, senza modifiche, su una macchina nota. Verificare i risultati del tool prima di permettere modifiche. Un modello può essere errato, anche se il tool funziona correttamente. Le credenziali, la memorizzazione dei dati, l’accesso alla macchina e l’approvazione da parte del tool sono aspetti separati; cambiare uno di questi non garantisce automaticamente l’accesso all’altro. In particolare, un endpoint di chat pubblico deve essere protetto come piattaforma per l’esecuzione remota.

Per informazioni sul percorso di connessione del client MCP, vedere [client connectivity](../clients/connectivity.md). Per informazioni sui parametri del tool, vedere [Tools reference](../reference/tools.md).
