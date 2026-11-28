<!-- i18n-source-sha256: 01c14c19cf5addf99299993b57542259bcb40bbfb13600758b516a86c89e716b -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Obiettivi, chat di routine e lavoro che richiede tempo per essere completato

## Scegli il meccanismo giusto.

| Meccanismo | Scopo |
|---|---|
| Generazione di conversazioni ordinarie | Risposta alle richieste attuali, inclusi i comandi da inviare al modello |
| Obiettivo della conversazione | Continuazione di una sessione logica attiva, anche al di fuori dei limiti di turno del modello |
| Conversazioni programmate | Avviare un Agente con un prompt salvato, in modo che operi secondo una sequenza periodica predefinita. |
| Esecuzione di compiti persistenti o di routine | Esecuzione di comandi indipendentemente dalle richieste del modello |
| Subagenti | Espedire una task limitata ad un altro thread di agente. |

Un chattaggio programmato non rappresenta un “job” persistente. Una “session logica”, invece, non è una conversazione né un processo operativo del sistema operativo. Annullare un chattaggio programmato non significa necessariamente interrompere tutto ciò che è stato avviato grazie a tali strumenti.

## Obiettivo della conversazione

Per compiti lunghi, è necessario chiedere all’Agent di definire un obiettivo concreto e di mantenere un piano di azione, utilizzando gli strumenti legati alla sessione logica. Il piano include le fasi da svolgere e lo stato di ciascuna fase. Il sistema di chat può continuare a eseguire il piano attivo anche quando il modello cambia posizione, senza dover aspettare che venga inviato un nuovo comando da parte dell’utente o che scada il tempo impostato per l’inattività dello strumento esterno MCP Live Workspace.

È necessario ispezionare il piano e i progressi ottenuti. È possibile interrompere, riprendere o annullare l’attività utilizzando i controlli disponibili per ogni obiettivo. La continuazione dell’attività richiede che il piano sia ancora attivo e che l’operazione possa essere eseguita; non è quindi possibile continuare con un piano già completato, bloccato o annullato. Le risposte ripetute senza alcun progresso causano un’interruzione dell’attività, piuttosto che una situazione di ciclo infinito (attualmente, questo avviene dopo tre tentativi senza risultati). È necessario risolvere il problema che sta bloccando l’attività prima di riprenderla.

Definire i criteri di completamento. Ad esempio: ispezionare il repository, implementare le correzioni necessarie, eseguire l’insieme di test appropriato e segnalare eventuali errori. Chiedere all’Agente di registrare esattamente gli ID delle commit e i risultati dei test, invece di considerare il processo completato soltanto in base al proprio piano.

Il meccanismo di gestione dei client esterni del MCP è separato; per informazioni più dettagliate, si veda [Human interface](../guides/human-interface.md) per quanto riguarda il flusso di lavoro legato alla consegna delle sessioni logiche e degli spazi di lavoro live.

## Creare una chiamata di chat programmata

![Barra laterale delle chat pianificate con una pianificazione di esempio disattivata](../assets/chat/scheduled-chats.png)

Apri la gestione dei chatter programmati. Crea un calendario con un nome descrittivo, un agente da utilizzare, un prompt, la zona fuso oraria e il ritmo di svolgimento delle conversazioni. Seleziona l’oggetto della conversazione; opzionalmente, puoi selezionare un progetto per iniziare una nuova conversazione. Salva e abilita il calendario. Utilizza il controllo dell’esecuzione manuale per verificare la configurazione prima di utilizzarlo.

Le modalità di esecuzione supportate includono: orari orari, giornalieri, nei giorni feriali, settimanali, cronologia a cinque campi e esecuzione continua. L’esecuzione continua inizia per le successive occorrenze, dopo il tempo di ritardo configurato; un tempo di ritardo pari a zero può causare un carico continuo sul provider e sulla macchina. Gli orari di esecuzione regolari prevedono un intervallo minimo di cinque minuti. È necessario utilizzare un fuso orario specifico IANA, ad esempio `Asia/Shanghai` o `UTC`; è possibile verificare l’orario della prossima esecuzione dopo aver salvato le impostazioni.

Esempio cron per le 09:00 nei giorni feriali:

```text
0 9 * * 1-5
```

Questo utilizza il fuso orario selezionato, ma non necessariamente quello del sistema del Controller. È importante verificare se il fuso orario scelto segue le regole del fuso orario di hora leggera.

## Obiettivi della conversazione

- **Nuova conversazione a ogni esecuzione:** è possibile avviare una conversazione separata per ogni singola situazione; questo è utile per creare rapporti dettagliati su ciascun caso.
- **Riutilizzare una conversazione:** è possibile creare una conversazione già esistente durante la prima utilizzazione di questo strumento, e poi riutilizzarla per le successive occasioni di utilizzo. È un metodo utile per il monitoraggio cumulativo dei dati.
- **Usare una conversazione esistente:** selezionare una conversazione già in corso, alla quale verranno assegnati dei turni per la partecipazione.

Una conversazione già esistente o riutilizzata può crescere nel tempo e richiedere una qualche forma di “compressione” dei contenuti. È meglio utilizzare chat indipendenti quando il contesto storico non è necessario. Le operazioni programmate dipendono dal canale scelto per l’agente e dal modello utilizzato; inoltre, è importante assicurarsi che tali canali siano ancora disponibili e utilizzabili.

## Permessi non gestiti

L’esecuzione pianificata appartiene al Controller e utilizza i nomi degli scope autorizzati salvati anziché conservare un token di accesso del browser. Salvare o avviare manualmente una pianificazione per autorizzarla, se necessario. Si applicano i permessi macchina dell’Agent designato; le normali eccezioni macchina del progetto o della chat non costituiscono la politica macchina della pianificazione. Le restrizioni del Controller, l’autorizzazione salvata, le capacità e le approvazioni degli strumenti restano applicabili.

Per i server MCP esterni che richiedono autenticazione, un accesso interattivo non implica automaticamente un’autorizzazione rinnovabile per l’esecuzione non presidiata. Se l’interfaccia di pianificazione richiede una nuova autenticazione o un accesso non presidiato, risolvere le credenziali specifiche del server o rimuovere la dipendenza prima di abilitare la pianificazione. Non riutilizzare i token del browser come sostituti.

È necessario utilizzare un agente di monitoraggio in modalità “read-only”. È importante descrivere chiaramente quali siano gli obiettivi consentiti, quali siano i risultati desiderati e quali azioni devono essere evitate. Se una task programmata richiede l’intervento o l’approvazione umana, è necessario verificare le interazioni in corso; non si deve assumere che l’esecuzione senza controllo significhi un accesso illimitato. Esempio di prompt di monitoraggio:

```text
Ispezionare il lavoro di addestramento specificato, nonché i relativi log di operazioni.
Riferisce lo stato attuale del sistema, i livelli di perdita, il throughput, l’orario previsto per la consegna dei prodotti, nonché eventuali nuovi errori che potrebbero verificarsi.
Non modificare i file, non riavviare il processo o non avviare nuove operazioni.
Se i dati non sono disponibili, è necessario indicare esattamente il motivo per cui non possono essere forniti.
```

## Ciclo di vita e recupero

Il Controller gestisce i calendari, lo stato delle operazioni e le transazioni relative alle richieste ricevute, al fine di evitare l’effetto di ripetizioni delle stesse operazioni. Non è necessario che una scheda del browser rimanga aperta. Non si deve assumere che le operazioni mancate vengano sempre riprodotte, né che tutti i dati esterni sopravvivano anche dopo il riavvio del Controller. È importante verificare l’ultima esecuzione, la prossima esecuzione, le operazioni in corso e i messaggi di chat relativi al periodo di interruzione.

Disattiva i cronogrammi per evitare che si verifichino in futuro. È necessario verificare separatamente ogni singolo evento in corso di esecuzione; interrompere la gestione dei cronogrammi non garantisce l’annullamento dell’operazione in corso. Elimina i cronogrammi che non sono più necessari e revoca i permessi dell’agente non più utilizzati.

Un lavoro o un terminale creato da un WebUI Agent può continuare a funzionare anche dopo la completazione della risposta al modello richiesto. Un semplice riavvio del controller non è sufficiente per terminare il lavoro svolto dall’Agente. Un abbandono esplicito, la perdita dei permessi necessari per l’esecuzione del lavoro o l’esaurimento dei diritti di accesso possono causare l’annullamento dei lavori svolti dall’Agente. Se il lavoro è offline, l’annullamento potrebbe rimanere in sospeso fino a quando il lavoro non può essere completato nuovamente. È necessario verificare il lavoro o il terminale stesso prima di dichiarare che l’esecuzione è terminata. L’Agente può inviare o interrompere soltanto i lavori svolti tramite il meccanismo protetto fornito dal WebUI. I client MCP esterni mantengono la loro semantica originale.

Gli strumenti di background dell’agente e le attività sottogestionate hanno ciascuno il proprio ciclo di vita. Un risultato può rimanere “in sospeso” anche dopo la fine dell’esecuzione; è quindi necessario controllare lo stato delle attività di background e recuperare il risultato richiesto. Non si dovrebbero creare nuove attività semplicemente perché il risultato non è ancora visibile.

Per i comandi che devono essere utilizzati per un periodo di tempo prolungato, è necessario utilizzare i lavori gestiti da LSM o terminali persistenti. Salvare l’output in un file di log, registrare gli identificatori dei lavori e verificare il progresso effettivo del lavoro. Vedere [Modelli di utilizzo](../guides/usage-patterns.md).
