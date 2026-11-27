<!-- i18n-source-sha256: e5ebd5f8cfb42332f4e38d63eabe47a6274ceacf919130202203bd85917f3469 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Tool, macchine e permessi.

## Livelli di autorizzazione.

Uno strumento elencato nell’elenco non garantisce necessariamente il permesso di utilizzarlo. L’autorizzazione effettiva dipende da diversi fattori: le restrizioni imposte dal controller, i diritti dell’utente autenticato, le politiche imposte dalla macchina, le funzionalità offerte dall’agente, nonché l’approvazione dello strumento stesso. Le semplici istruzioni fornite non bastano per garantire l’accesso.

Le macchine registrate, compreso il “local Controller Target” quando è abilitato, hanno per impostazione predefinita diritti di lettura/scrittura sulla macchina di chat. Tuttavia, è possibile limitare questi diritti nelle situazioni in cui le informazioni scritte su tali macchine possono essere considerate sensibili. I nomi delle macchine sconosciute non ricevono alcun tipo di autorizzazione implicita. Il Controller può disattivare l’esecuzione locale o l’utilizzo dei lavoratori remoti, a seconda delle esigenze.

## Accesso alle macchine

| Accesso | Significato |
|---|---|
| Nessuno | Le operazioni sulle macchine sono indisponibili |
| Sola lettura | Sono consentite soltanto le operazioni classificate come “solo lettura”; l’esecuzione di comandi shell o Python non rientra tra le operazioni consentite. |
| Leggere/scrivere | Consente la lettura e la modifica/esecuzione delle operazioni, ma con alcune limitazioni. |
| Eredita | Utilizzare i valori predefiniti, piuttosto che impostazioni esplicite. |

![Permessi e modalità di approvazione delle macchine durante una conversazione](../assets/chat/machine-permissions.png)

Impostare i valori predefiniti globali e le eccezioni per progetto e per chat nei controlli dei permessi delle macchine. Le eccezioni di una conversazione hanno precedenza su quelle del progetto, che a loro volta precedono i valori globali. Un Agent può limitare ulteriormente l’accesso per macchina o tramite la propria politica predefinita; i suoi permessi espliciti non aggirano le restrizioni dell’identità autenticata né del Controller.

Esempio: una politica globale di lettura/scrittura, un’eccezione del progetto di sola lettura e un Agent con permesso di lettura/scrittura producono accesso in sola lettura nella chat del progetto, salvo un’esplicita eccezione della conversazione. Un’eccezione di lettura/scrittura nella conversazione non può comunque superare il limite di sola lettura dell’Agent.

Un’esecuzione programmata con un Agente specificato utilizza le impostazioni di quel Agente, nonché gli ambiti di esecuzione salvati, invece di ereditare le impostazioni standard dell’agente di chat. Per ulteriori informazioni, vedere [Obiettivi e automazione](automation.md). Utilizzare un Agente dedicato per le operazioni non supervisionate.

## Approvazione del strumento

| Moda | Comportamento |
|---|---|
| Automatico | Le chiamate effettuate tramite gli strumenti autorizzati procedono senza alcun ulteriore processo di approvazione, a meno che una politica specifica non lo richieda. |
| Esaminare le operazioni rischiose | Il controllore richiede un’ispezione delle operazioni classificate come pericolose, tra cui i comandi shell arbitrari e molte chiamate esterne. |
| Esamina tutti gli strumenti | È necessario ottenere l’approvazione per le richieste di utilizzo degli strumenti ordinari. |

Le impostazioni di approvazione della chat possono ereditare quelle dell’Agent e quelle globali. Le regole esplicite di rifiuto o approvazione restano valide. Un Agent figlio non può rendere meno restrittiva la modalità di approvazione del genitore. L’approvazione è indipendente dai permessi: approvare un’azione su una macchina negata non concede accesso alla macchina.

È necessario esaminare attentamente gli argomenti trattati, la destinazione e i possibili effetti collaterali prima di approvare il processo di approvazione. Per un flusso di lavoro non gestito da un sistema automatizzato, è importante configurare con cura l’agente incaricato della procedura di approvazione. L’approvazione da parte di una persona può ritardare i progressi del processo. Non si dovrebbe ampliare l’accesso soltanto per eliminare i messaggi di avviso.

## Strumenti MCP nativi e esterni

I tool nativi operano sul Controller e sui lavoratori registrati, attraverso LSM. Il registro dei tool include funzionalità per le operazioni con i file, l’uso della shell e dei job, le operazioni con il browser e la GUI, la scoperta remota delle macchine, le sessioni logiche e altre funzioni. Per informazioni dettagliate sui schemi di argomenti utilizzati, si può consultare [Tools reference](../reference/tools.md). Per informazioni su come collegare le macchine, si può invece consultare [Remote workers](../guides/remote-workers.md).

È possibile gestire i server MCP annidati nell’ambiente WebUI. Le configurazioni supportate includono l’uso di standard input locali e protocolli HTTP remoti; inoltre, è possibile utilizzare variabili d’ambiente o intestazioni specifiche per ciascun server. È anche possibile abilitare la funzionalità MCP esterna nei chat e negli agenti correlati. L’agente può scoprire, ispezionare e utilizzare gli strumenti esterni disponibili; tuttavia, l’autorizzazione e l’approvazione per l’uso di tali strumenti rimangono valide.

Uno strumento MCP esterno può operare indipendentemente dalle ACL native delle macchine: un’API esterna remota può modificare risorse anche quando l’accesso locale alle macchine è disabilitato. Verificare separatamente i permessi e le credenziali del servizio esterno. Non installare server stdio non affidabili su un Controller che contiene file sensibili.

## Chiedere all’utente se desidera utilizzare le funzionalità disponibili.

“Ask User” permette all’Agent di richiedere un input umano strutturato, invece di fare delle supposizioni. La risposta viene fornita utilizzando il controllo relativo alla domanda presentata. Si tratta quindi di una richiesta di informazioni, non di un permesso per aggirare uno strumento che è stato negato. Quando il compito non viene gestito manualmente, è necessario istruire l’Agent su come gestire le situazioni incerte e verificare le interazioni in corso prima di considerare il compito completato.

Il compositore permette di controllare diverse funzionalità, come la ricerca su rete, l’accesso ai dati esterni e la memoria disponibile per il modello. Questi controlli determinano quali funzionalità sono disponibili per il modello; essi sono separati dall’autorizzazione dei dati. Disattivare una funzionalità non elimina i risultati storici ottenuti. La ricerca su rete è abilitata per impostazione predefinita e utilizza strumenti web di lettura esclusiva, come descritto in [Network search](../guides/webui-network-search.md).

## Auditoria e verifica

Ispezia i richiesti effettuati dal tool e i risultati ottenuti; espandi i dettagli quando si analizzano i problemi che possono verificarsi durante l’esecuzione dei compiti. Il log di audit del controller registra le attività svolte dal tool; inoltre, i dati relativi ai compiti eseguiti mostrano chiaramente come vengono gestite le operazioni. Un risultato positivo dell’API significa che il tool è riuscito a fornire un risultato desiderato, ma non necessariamente che l’operazione richiesta sia stata completata con successo. Verifica indipendentemente i dati relativi alle operazioni eseguite, allo stato dei compiti e alla salute della distribuzione. Per maggiori informazioni, consultare [Audit Log](../guides/audit-log.md).
