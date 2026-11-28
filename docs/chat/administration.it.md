<!-- i18n-source-sha256: 91fa7e8e41354be2761864ffe05d1efb85063953c79a40065ad61661cc15b836 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Amministrazione e risoluzione dei problemi

## Architettura di distribuzione

Il frontend WebUI è servito dal controller Python, nello stesso origin del resto dei endpoint REST e MCP. Il backend di default utilizzato è SQLite. I binari rilasciati includono anche i file necessari per il funzionamento del frontend; per crearli da zero è necessario utilizzare l’ambiente di sviluppo JavaScript, senza dover eseguire il controller installato. Non sono necessari Node.js, MongoDB, Meilisearch, né alcun backend separato come LibreChat.

Si possono utilizzare le istruzioni fornite in [Quickstart](../getting-started/quickstart.md) e [Reference di configurazione](../reference/configuration.md). Per i build basati sul codice sorgente, si consiglia di consultare le istruzioni fornite nella sezione [WebUI build instructions](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## Garantire la distribuzione sicura dei componenti necessari per il funzionamento del sistema.

È necessario utilizzare un proxy inverso HTTPS affidabile, o addirittura un tunnel di comunicazione protetto. È anche importante utilizzare metodi di autenticazione sicuri e codici segreti robusti. Il controller deve essere conservato all’interno di un container o di una macchina virtuale adeguata. È necessario limitare l’accesso in entrata e proteggere le credenziali di uscita. Non è consigliabile esporre un endpoint di esecuzione non autenticato sul Internet pubblico.

Un proxy deve essere in grado di gestire le risposte in modalità streaming, senza necessitare di memorizzarle nel buffer fino alla loro completa elaborazione. Inoltre, deve supportare l’utilizzo delle funzionalità WebSocket per gli interfacce che ne richiedono l’uso. È necessario impostare tempi di timeout adeguati per le richieste lunghe e per le operazioni di caricamento dei dati; inoltre, è importante permettere dimensioni di carico dei file consone alle esigenze del sistema. Il URL pubblico configurato deve essere coerente con l’origine del browser e con i codici di callback forniti da OAuth. Non è consigliabile disattivare globalmente le verifiche dei certificati per risolvere eventuali problemi legati al TLS.

I richieste vengono inviati al Controller. I messaggi, i file allegati e i risultati ottenuti tramite l’API possono essere inviati all’API sottostante selezionata. È necessario valutare attentamente le condizioni relative alla gestione dei dati del fornitore prima di utilizzare contenuti confidenziali. Inoltre, è importante proteggere i segreti legati all’MCP e i token utilizzati per invitare i lavoratori.

## Stato, backup e aggiornamento

Il percorso di archiviazione predefinito è `.local-shell-mcp`, che si trova all’interno dello spazio di lavoro configurato. Il valore `LOCAL_SHELL_MCP_STATE_DIR` può essere modificato per cambiare il percorso di archiviazione. La base di dati condivisa è `lsm.sqlite3`. I messaggi di chat, i progetti, le impostazioni, gli agenti, la memoria, le cronologie e lo stato di esecuzione vengono memorizzati sul server. Gli allegati, i file dello spazio di lavoro e altri elementi possono invece essere archiviati al di fuori della base di dati.

Eseguire il backup completo del directory degli stati, con l’ambiente di distribuzione e i file rilevanti per lo sviluppo inclusi nel backup. Considerare i backup come elementi sensibili. Un backup esclusivamente relativo alla base di dati può trascurare gli allegati e le configurazioni presenti nel database. È necessario utilizzare un meccanismo di backup affidabile, come quello basato su SQLite. Copiare soltanto il file principale del database SQLite può permettere di omettere i contenuti WAL già commessi. Verificare i backup ripristinando il sistema in un ambiente di prova isolato.

Prima di effettuare l’aggiornamento, registrate la versione attuale del sistema, il percorso di esecuzione, le impostazioni, la posizione della connessione e tutti i lavori in corso di esecuzione. Fermate o eliminateli temporaneamente, create una copia di backup completa dell’installazione, aggiornate l’installazione stessa e verificate nuovamente l’autenticazione, il history delle chat, la generazione dei modelli, le operazioni in streaming, i lavoratori e le task programmate. La migrazione da uno stato a un altro è possibile durante l’avvio del sistema; conservate i file esistenti fino a quando non avete verificato che la migrazione è completata correttamente. Non sostituite il directory dei dati di produzione con uno directory di test vuoto.

Il rollback non consiste semplicemente nel modificare il file binario, se una migrazione del database ha causato un cambiamento nello stato persistente della base di dati. È necessario ripristinare lo stato compatibile quando necessario, e evitare di utilizzare due controller configurati separatamente nello stesso storage live.

## La diagnosi indica che il chatt non è riuscito.

| Sintomo | Prima di procedere, verificare tutto. |
|---|---|
| Non è possibile caricare l’interfaccia utente. | Processo di controllo, pacchetto frontend, URL corretta, proxy e autenticazione |
| Il modello non è presente. | Configurazione del canale, scoperta dei modelli, identificazione dei modelli, autorizzazione dell’account |
| HTTP 401/403 da parte del fornitore | Chiave/account API, permessi del fornitore, canale selezionato e protocollo utilizzato |
| HTTP 429 | Limiti di velocità/quotazioni in direzione opposta, richieste simultanee, stato dell’account/piano |
| HTTP 400/413/422 | Si richiede la compatibilità con i diversi formati di input, le dimensioni del contesto in cui il sistema opera, nonché i limiti legati alle dimensioni degli allegati. Inoltre, sono necessari i parametri specifici del modello utilizzato. |
| Errore HTTP 5xx o timeout. | Condizioni legate alla salute del provider, rete, capacità di elaborazione dei dati, timeout dei proxy. |
| La trasmissione dei dati si interrompe. | Necessario ripristinare la connessione; verificare lo stato della generazione dei dati e gli errori riscontrati. |
| Lo strumento non è disponibile. | Opzioni disponibili: capacità degli agenti, lista delle autorizzazioni della macchina, ambiti di accesso basati su OAuth, commutatori del controller. |
| Lavoratore offline | Registro dell’operatore, connessioni esterne, log di Heartbeat e log del controller |
| Richiesta di approvazione/risposta ancora in sospeso. | È possibile aprire la conversazione e verificare l’azione richiesta. |
| Il programma di scheduling non viene eseguito. | Stato attivo, zona fuso orario, Agente/Canale, obiettivo, autorizzazione salvata, ultima esecuzione. |

Non assumete che tutti gli errori HTTP provengano dalla stessa servizio: è necessario distinguere tra un fallimento nell’accesso al sistema LSM, un errore nella API del modello upstream, un errore esterno legato al MCP e un errore nel trasporto dei dati da parte del Worker. Verificate i dettagli degli errori e i log relativi al controller; inoltre, trattate con cautela i codici di accesso, i token di autenticazione e gli URL di callback prima di condividerli con altri.

## Ripristino e recupero dei provider

Prima dell’inizio di una risposta del modello, gli errori transitori di connessione e alcuni errori HTTP (408, 429, 500, 502, 503, 504) possono essere gestiti con nuovi tentativi e attese limitate. Gli intervalli ordinari attuali sono 1, 2, 4, 8, 16, 30, 30 e 30 secondi (otto tentativi dopo la richiesta iniziale). HTTP Retry-After può prolungare un’attesa fino a 120 secondi; alcuni errori di streaming aggiungono variazioni casuali. Il limite si applica alla singola richiesta al modello, non all’intera conversazione. La compattazione ha un proprio percorso di recupero. Un limite dovuto a crediti esauriti può persistere fino al rinnovo della quota da parte del provider. I tentativi automatici non garantiscono il successo e non rendono illimitato un abbonamento.

Un’interruzione durante l’esecuzione del programma è diversa da un errore che si verifica prima del primo evento di risposta. Non si può affidare alla riproiezione automatica di una sequenza di comandi parzialmente eseguita. È necessario verificare il contenuto dei dati salvati e lo stato esterno del programma, prima di tentare nuovamente l’esecuzione. Se l’esecuzione è ancora attiva, è meglio riconnettersi al sistema, piuttosto che iniziare un nuovo processo. Se l’esecuzione si è interrotta per causa di errori, è necessario utilizzare i controlli di recupero/ripetizione appropriati, oppure iniziare un nuovo processo con una comunicazione manuale, se il processo originale non può continuare.

I problemi legati alla compattazione del contesto dovrebbero essere indagati separatamente dagli errori normali legati alla generazione dei modelli. È necessario verificare il limite di memoria effettivo, la compatibilità tra i modelli, i risultati ottenuti da strumenti troppo potenti, nonché il limite di spazio disponibile. Per ulteriori informazioni, consultare la sezione [Memoria e contesto](context.md).

## Cosa è necessario includere nella segnalazione dei bug?

Indicate la versione e l’autore del software utilizzato, il metodo di installazione, il sistema operativo, il tipo di protocollo utilizzato, il tipo dell’endpoint protetto, l’ID del modello, l’orario approssimativo, le fasi necessarie per riprodurre il problema, lo stato delle conversazioni/operazioni in corso, nonché i dettagli degli errori riscontrati. Per i problemi che riguardano la rete, indicare anche la versione del software utilizzato, il nome della macchina e lo stato dei messaggi di controllo. Se possibile, fornire anche una breve descrizione del problema da riprodurre. Non inviare mai chiavi API, token OAuth, informazioni personali o altri dati personali.
