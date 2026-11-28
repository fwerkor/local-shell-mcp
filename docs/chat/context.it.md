<!-- i18n-source-sha256: 214687d6067b7dc2dd2b6eec1a207aa50be3ab9550d081f8a60e3013684c0250 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Memoria, contesto e utilizzo dei token

## Tre tipi diversi di stato

| Stato | Scopo |
|---|---|
| Storia delle conversazioni | I messaggi originali e le attività svolte dal controller sono salvati. |
| finestra di contesto | Il sottoinsieme di istruzioni, schemi di strumenti, informazioni storiche, riassunti e altri dati inviati in una specifica richiesta di modello. |
| Memoria persistente | I fatti e le preferenze che possono essere riutilizzati, e quindi accessibili durante le conversazioni, all’interno dello stesso ambito di memoria relativo. |

Una lunga conversazione salvata può superare la dimensione del “quadro di contesto” del modello, senza che tutta la storia della conversazione venga persa. La memoria non significa che l’intera storia delle conversazioni venga inviata a ogni richiesta del modello.

## Gestisci la memoria

![Barra laterale di gestione della memoria con una voce di esempio](../assets/chat/memory-management.png)

La memoria è abilitata per impostazione predefinita, a meno che non venga disabilitata dalle impostazioni dell’utente, dalla funzione di connessione al chat o da restrizioni legate alle capacità dell’Agente. È possibile utilizzare la pagina di gestione della memoria per esaminare e modificare le informazioni memorizzate. Si consiglia di chiedere all’Agente di memorizzare informazioni utili, convenzioni o preferenze legate ai progetti, e di verificare i risultati nella interfaccia di gestione della memoria.

Quando si modifica un’entità di memoria, è necessario utilizzare una chiave composta esclusivamente da lettere minuscole e trattini (ad esempio, `repository_conventions`). Il limite di lunghezza predefinito per le chiavi è di 10.000 caratteri; l’installazione può però configurare autonomamente i limiti legati alla memoria disponibile per lo storage delle informazioni. Se una chiave viene rifiutata, è necessario verificare il motivo dell’errore, piuttosto che cercare di dividere le informazioni segrete in più chiavi.

La memoria può utilizzare sia un pool personale condiviso, sia uno spazio di memoria specifico per ciascun agente, a seconda della configurazione dell’agente stesso. Non è consigliabile memorizzare chiavi API, password o altri dati sensibili nella memoria. Disattivare la memoria impedisce che questi dati vengano utilizzati nel contesto corrispondente; ciò non equivale alla cancellazione delle informazioni memorizzate o alla rimozione delle informazioni presenti nella cronologia delle conversazioni.

Quando la modella viene esposta, utilizza `set_memory` per creare o aggiornare degli elementi memorizzati; un valore vuoto permette di eliminare tali elementi. `find_memory`, invece, recupera gli elementi memorizzati in base a una query o a una chiave specifica. Una query vuota, infine, elenca tutti gli elementi memorizzati. La flag opzionale `include_conversations` permette di cercare anche i testi presenti nelle altre conversazioni. La paginazione avviene utilizzando `page` (valore predefinito: 1) e `limit` (valore predefinito: 10, massimo 50). Il recupero degli elementi memorizzati avviene basandosi sui testi delle conversazioni, piuttosto che sui record relativi alle operazioni eseguite dal tool. Il recupero è effettuato in base alla rilevanza dei dati recuperati; quindi, se necessario, è utile utilizzare nomi o termini specifici per affinare la query.

L’iniezione automatica di informazioni memorizzate è mantenuta costante durante le varie fasi di una conversazione, al fine di preservare i prefissi utilizzati per gli prompt dei provider. Modificare le informazioni memorizzate non altera in alcun modo i dati già presenti nella memoria. Il recupero esplicito delle informazioni memorizzate permette di accedere ai dati attualmente disponibili; è possibile iniziare una nuova conversazione se necessario, per utilizzare i nuovi dati memorizzati.

## Capacità di contesto

È necessario definire il limite di contesto effettivo di ciascun modello nel proprio canale. Il controller stima l’input visibile del modello e riserva spazio per l’output; la configurazione di budget attuale prevede un rapporto di compressione del 85% e un rapporto di riserva del 5%. Tuttavia, questi valori possono variare a seconda delle configurazioni effettive del modello e delle condizioni di esecuzione. Il calcolo potrebbe essere approssimativo, soprattutto per casi in cui il tokenizer non è familiare, oppure per richieste multimediali o schemi specifici del fornitore.

La composizione del contesto può includere istruzioni del sistema, configurazioni degli agenti, definizioni dei strumenti, file allegati, messaggi precedenti e risultati ottenuti dagli strumenti stessi. Un fornitore può utilizzare un tokenizer diverso o considerare altri elementi interni. Si tratta di una guida operativa, non di una garanzia fornita dal fornitore stesso.

## Compattamento automatico

Quando il budget del contesto richiede una riduzione delle dimensioni dei dati, il controller crea o aggiorna un riassunto dei dati relativi al contesto precedente. In questo modo, vengono conservati i dati più recenti per le future richieste di modellazione. Il riassunto cerca di preservare gli obiettivi, i vincoli, le decisioni prese, i progressi ottenuti, gli identificatori rilevanti, i risultati ottenuti grazie agli strumenti utilizzati e le azioni successive da intraprendere. I dati originalmente salvati rimangono disponibili per l’ispezione; il riassunto, invece, rappresenta una semplificazione dei dati forniti dalla modellazione, e non una riproduzione perfetta dei dati originali.

La compressione avviene prima del successivo richiesta, e questo riduce il volume di dati da gestire. Se la compressione fallisce, l’engine riprova il processo di compressione, in base alle regole di gestione degli errori. Non è necessario continuare con un input già troppo grande. È importante verificare lo stato di compressione e i possibili errori che potrebbero verificarsi. I messaggi recenti e le relazioni tra strumenti utilizzati devono rimanere coerenti. I risultati dei vecchi strumenti non devono essere ricreati continuamente, soltanto per ridurre il volume di dati da gestire.

Anche un singolo file o risultato di strumento può superare i limiti imposti. È consigliabile richiedere un output limitato, range di file specifici o un riassunto dei dati. I risultati più grandi possono essere salvati in file separati, e le informazioni necessarie possono essere recuperate in modo semplice, invece di dover essere inserite continuamente nel contesto del modello.

## L’uso cumulativo dei dati e i tassi di cache sono importanti da considerare.

La visualizzazione dell’uso della sessione e la finestra di dialogo rappresentano rispettivamente informazioni diverse. L’uso degli input/output si accumula durante le richieste successive, inclusi i contesti ripetuti. Le metriche di cache descrivono il caching dei dati forniti dal provider, se disponibili. La occupazione del contesto del modello misura l’attività del modello attuale, e non include tutti i dati gestiti in passato.

Ad esempio, una richiesta che contiene 20.000 token di input, seguita da un’altra richiesta che contiene 25.000 token di input, consuma complessivamente 45.000 token di input. Tuttavia, la seconda richiesta utilizza soltanto circa 25.000 token del proprio contesto di memoria. I token memorizzati non sono gratuiti, a meno che il provider non lo preveda nel suo prezzo. Un limite più elevato per il contesto del modello cambia la capacità di gestione dei dati, ma non influisce sull’uso effettivo dei dati già gestiti in passato.

La compattazione può ridurre l’occupazione attuale dei dispositivi, ma allo stesso tempo aumenta il consumo energetico del modello stesso. Il cambio di modello modifica i limiti applicabili al contesto in cui il modello opera; tuttavia, il consumo precedente non viene eliminato. Se un provider omette i dati riguardanti l’utilizzo effettivo o i metadati relativi alla cache, le stime e le metriche potrebbero risultare incomplete. Per quanto riguarda la conciliazione dei dati finanziari, è necessario utilizzare i dati di fatturazione e i prezzi forniti dal provider, non soltanto quelli visualizzati nel LSM.

## Ridurre i costi e preservare i dati utili.

È necessario mantenere le istruzioni stabilizzate, evitare output troppo grandi e utilizzare metodi di recupero mirati. Iniziare una conversazione separata per lavori non correlati. Quando è necessario passare il controllo, salvare un file con informazioni dettagliate: percorsi esatti, identificativi dei dati recuperati, risultati ottenuti e domande ancora irrisolte. Verificare le informazioni importanti confrontandole con le fonti originali o i risultati ottenuti dal tool, piuttosto che affidarsi soltanto a un riassunto generato automaticamente.
