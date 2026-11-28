<!-- i18n-source-sha256: 012f0d9f7b350fcf47e3fd6afdf2fc9e7044ff28cb2eca7c029c3d6af35f3b04 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Conversazioni e progetti

## Creare e continuare una conversazione

È possibile aprire una nuova conversazione, scegliere un canale/modello o un Agente, e inserire un messaggio. Il chat funziona sul Controller, e le informazioni aggiornate vengono visualizzate nel browser. Riavviare la pagina o chiudere una scheda non equivale a annullare l’esecuzione dell’operazione in corso. È possibile utilizzare il pulsante “Stop” per interrompere l’esecuzione dell’operazione, e verificare lo stato del processo prima di avviare un’altra operazione.

Un chatt salvato mantiene l’associazione tra il modello utilizzato e l’agente responsabile della gestione del chat. È possibile cambiare il modello se si desidera un modello diverso. Una conversazione, invece, non rappresenta una “session logica”: essa contiene messaggi provenienti dall’utente e dal modello utilizzato per la gestione del chat. Una sessione logica, invece, contiene informazioni riguardanti gli obiettivi della task, i progressi o i piani di lavoro legati alla task stessa. È importante mantenere gli identificativi corrispondenti quando si passa una task complessa a qualcun altro.

## Organizzare e trovare il lavoro giusto

I progetti permettono di raggruppare le conversazioni correlate tra loro e di definire i permessi per l’accesso alle rispettive macchine. Un progetto può contenere più chat separate. È possibile spostare o creare chat all’interno del progetto appropriato, invece di presupporre che le conversazioni abbiano lo stesso contesto. Il progetto attivo può fornire informazioni all’Agente riguardo all’organizzazione delle conversazioni.

I tag permettono di classificare le conversazioni; i segnalini dei messaggi indicano i singoli messaggi, e permettono di tornare facilmente alle informazioni utili. Questi elementi sono separati dal meccanismo di “pinning” delle conversazioni. È possibile utilizzare i titoli dei messaggi, la ricerca, l’archiviazione dei messaggi e gli indicatori per indicare i messaggi non letti, al fine di mantenere una barra laterale facilmente gestibile.

L’archiviazione consente di spostare una conversazione fuori dalla lista normale, senza però eliminare il suo contenuto salvato. È possibile ripristinarla dall’interfaccia di archiviazione, quando necessario. La cancellazione di una conversazione è un’operazione distruttiva; quindi non utilizzarla come alternativa all’archiviazione. L’implementazione attuale utilizza il formato SQLite per memorizzare lo stato delle conversazioni; non si deve assumere che il vecchio formato di archiviazione sia ancora utilizzabile.

## Operazioni di messaggistica e esecuzione di compiti

I controlli disponibili per i messaggi dipendono dal messaggio stesso e dal suo stato attuale di esecuzione. È possibile modificare o riprovare una conversazione quando necessario, oppure eliminare una conversazione con un utente/assistente quando non è più necessaria. L’eliminazione delle conversazioni modifica il history delle conversazioni salvate e può influenzare i contenuti successivi; tuttavia, l’eliminazione delle conversazioni non può annullare comandi shell, operazioni di scrittura a distanza, push di dati su Git o altri effetti collaterali esterni.

Quando si riprova una operazione che ha fallito, è necessario leggere i dettagli degli errori e verificare prima le operazioni già eseguite. Se una operazione di scrittura potrebbe essere riuscita prima della disconnessione, è necessario verificare lo stato esterno prima di ripetere l’operazione. Se c’è un altro messaggio in coda o se una operazione è già in corso, è consigliabile utilizzare i controlli e gli indicatori di stato presenti, invece di assumere che più operazioni possano essere eseguite contemporaneamente nello stesso momento. Il pannello dei messaggi in coda permette di visualizzare le operazioni in sospeso; il controllo delle operazioni tenta di fornire indicazioni utili, dopo che le operazioni attualmente in corso sono terminate. Nessuna delle due operazioni può annullare gli effetti delle operazioni già completate.

## Attacchi, anteprime e elementi di riferimento

È possibile utilizzare il controllo relativo agli allegati per caricare file o immagini supportate. La funzionalità di caricamento limita l’importo massimo degli allegati a 32 MiB. Inoltre, i limiti imposti durante la distribuzione/richieste di proxy potrebbero ridurre ulteriormente tale limite effettivo. I file caricati vengono memorizzati nel Controller e possono essere referenziati tramite il modello corrispondente. L’interpretazione delle immagini richiede l’uso di un modello e di un provider in grado di accettare input di tipo immagine. Il caricamento di file non rappresenta, però, una concessione per l’accesso a file locali o remoti non correlati.

Quando si richiede un file generato, è necessario specificare la destinazione del file, il formato e il contenuto. È importante verificare che il file esista davvero prima di condividerlo. È possibile scaricare o visualizzare i file supportati presenti nei messaggi di chat, se disponibili. Un file generato da un “Worker” potrebbe dover essere trasferito al “Controller” o fornito tramite un link al file. Per maggiori informazioni, vedere [File links](../guides/file-links.md).

La rappresentazione degli artefatti può visualizzare React, HTML, SVG, Markdown e Mermaid in un pannello laterale, invece di mostrarli soltanto come codice. Nelle impostazioni degli artefatti dell’agente, “Normal” utilizza le istruzioni standard; “shadcn/ui” fornisce indicazioni riguardo alle librerie di componenti; “Custom”, invece, permette la visualizzazione del contenuto generato, senza le istruzioni integrate per l’artefatto. Il codice generato o il contenuto visualizzato deve essere considerato non affidabile; è quindi necessario verificarlo prima di utilizzarlo al di fuori della preview. Le previsioni e i download basati su file sono diversi dai risultati generati dall’UI.

Non caricare credenziali, chiavi private o documenti per i quali non si ha l’autorizzazione a inviarli al fornitore di servizi selezionato. La cancellazione degli allegati e dei messaggi di chat è una cosa separata dalla cancellazione dei file originali sul computer.

## Preferenze

I messaggi di chat e le preferenze degli utenti, come gli opzioni da attivare o disattivare e i comandi di tastiera, vengono gestiti tramite l’interfaccia WebUI. Tali informazioni vengono memorizzate sul server in cui l’interfaccia è implementata. È possibile configurare il comportamento della tastiera; è importante distinguere tra la invio di un messaggio e l’inserimento di una riga di spazio. Le opzioni da attivare o disattivare vanno configurate separatamente dalle autorizzazioni dell’agente. Per ulteriori informazioni, consultare le sezioni [Strumenti e autorizzazioni](permissions.md) e [Memoria e contesto](context.md).
