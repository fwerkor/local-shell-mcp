<!-- i18n-source-sha256: a40a962d4db93cc0aac03601ffd13b21ab3a504c9bff930ab4b8173c4cfa4537 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Canali e modelli

## Configurare un canale

Apri il menu di selezione dei modelli in Chat e seleziona “Gestione canali”. Clicca su **Aggiungi canale**, scegli il tipo di connessione desiderata, inserisci le informazioni necessarie e salva il tutto. Seguire le istruzioni per selezionare un modello per il nuovo chat. Per creare un Agente personalizzato, invece, seleziona il canale e il modello nella configurazione dell’Agente.

I canali sono di proprietà del controller, e non rappresentano configurazioni di chat personali. Nelle implementazioni autenticate, la gestione dei canali richiede l’uso dello scope `admin:config`. Un amministratore può configurare i canali condivisi, senza dover distribuire chiavi API agli utenti che utilizzano il servizio di chat.

![Aggiungere un canale modello nella finestra di configurazione del canale](../assets/chat/channel-settings.png)

Un canale API normale possiede un nome, il protocollo del provider, l’URL di base, le credenziali e gli identificatori del modello. È necessario utilizzare una chiave API rilasciata per l’endpoint selezionato, e non la password dell’account LSM. L’account LSM invia le richieste tramite il Controller; un URL funzionante sul proprio laptop potrebbe non funzionare sul Controller.

| Protocollo | Esempio di URL di base per l’API | Utilizzo |
|---|---|---|
| OpenAI Chat Completions | `https://api.openai.com/v1` | Gateway compatibili con OpenAI e server locali per l’inferenza |
| OpenAI Responses | `https://api.openai.com/v1` | Un gateway che permette l’accesso all’API “Responses” |
| Nativo antropico | `https://api.anthropic.com/v1` | API compatibili con i messaggi antropici. |
| Nativo di Google Gemini | `https://generativelanguage.googleapis.com/v1beta` | API compatibili con Gemini generateContent. |

È necessario utilizzare l’URL di base richiesto dal provider, invece di inserire un URL completo per la richiesta di generazione dei risultati, come ad esempio un URL che termina con `/chat/completions`. Un provider che si dichiara compatibile con OpenAI potrebbe supportare soltanto le funzionalità legate alle risposte, non alle risposte generate automaticamente, né alle operazioni di streaming, ai dati multimediali o alle opzioni di ragionamento. È importante scegliere il protocollo che il provider effettivamente supporta. Gli esempi di URL forniti sono solo esempi, e non rappresentano una garanzia di accesso gratuito o disponibilità delle funzionalità.

## Endpoints locali e personalizzati.

Per un server compatibile con OpenAI che è collegato direttamente al Controller, l’URL di base potrebbe essere `http://127.0.0.1:8080/v1`. Quando il server viene eseguito in Docker, “loopback” si riferisce a quel container, e non all’host fisico su cui è installato il server. È necessario utilizzare un indirizzo accessibile dal namespace di rete del Controller. La registrazione di un lavoratore remoto da solo non garantisce che l’API di inferenza sia effettivamente disponibile.

Il validatore dell’URL del modello richiede il protocollo HTTPS, ad eccezione dei casi in cui si utilizza HTTP su host locali (`localhost`, `127.0.0.1`, `::1`). Un endpoint HTTP su un indirizzo LAN o su un nome di servizio Docker deve essere esposto tramite un gateway HTTPS. La funzionalità relativa all’endpoint privato Hosted Chat non è più disponibile. Gli URL di base non devono contenere credenziali, frammenti o stringhe di query.

Utilizzare TLS per gli endpoint remoti; limitare l’accesso soltanto a gateway privati affidabili. Verificare anche i nomi dei modelli utilizzati con il server di inferenza. Non inserire mai le chiavi API nei prompt, nelle screenshot, nelle stringhe di query o nella configurazione pubblicata. Lasciare vuota la chiave API quando si modifica un canale esistente, per poter conservare la chiave salvata; utilizzare una connessione senza chiave soltanto quando il servizio lo permette.

## Impostazioni predefinite configurate dall’ambiente di lavoro.

Il profilo integrato di OpenAI può essere configurato prima dell’avvio del servizio, utilizzando `LOCAL_SHELL_MCP_MODEL_BASE_URL` (o `OPENAI_BASE_URL`), `LOCAL_SHELL_MCP_MODEL` e `LOCAL_SHELL_MCP_MODEL_API_KEY` (o `OPENAI_API_KEY`). I profili integrati di Anthropic e Google possono utilizzare rispettivamente `ANTHROPIC_API_KEY` e `GOOGLE_KEY` / `GOOGLE_API_KEY`. I profili integrati hanno priorità sugli impostazioni derivate dall’ambiente di lavoro; utilizzare canali con nomi specifici per i vari endpoint indipendenti. Le impostazioni predefinite configurate dall’ambiente di lavoro non rappresentano una soluzione efficace per proteggere le chiavi del servizio.

## Autorizzazione dell’account ChatGPT.

Il canale account/Codex utilizza un flusso di autorizzazione basato su un account ChatGPT supportato, invece di utilizzare una chiave API tradizionale. Iniziare l’autorizzazione dal modulo di gestione dei canali e accedere alla pagina ufficiale di autorizzazione. In una distribuzione locale, il processo di autorizzazione può avvenire automaticamente. Se il browser non riesce a raggiungere il listener, copiare l’intera URL del callback dalla barra degli indirizzi e inserirla nella finestra di autorizzazione. È prevista una falla di connessione all’indirizzo del listener in questo flusso di autorizzazione.

Trattare l’URL di callback come una credenziale: non inviarlo mai in una chat e non pubblicarlo. Il Controller conserva l’autorizzazione sul server e rinnova le credenziali quando possibile. Autorizzare nuovamente l’account se scade o se l’accesso viene revocato. I modelli disponibili, i limiti del piano e gli usi consentiti sono stabiliti dal servizio account a monte; LSM non fornisce quote di abbonamento aggiuntive.

## Scoperta dei modelli e limiti legati al contesto

È possibile abilitare la scoperta automatica per richiedere informazioni sul modello al fornitore. Il controller aggiorna tali informazioni periodicamente (attualmente ogni dieci minuti); è anche possibile effettuare aggiornamenti manuali. I dati non trovati vengono comunque conservati. Se il fornitore non dispone di un endpoint per l’elenco dei modelli compatibili, è necessario disattivare la funzione di scoperta e inserire manualmente gli identificatori dei modelli, uno per riga.

Il rilevamento riconosce i metadati espliciti della finestra di contesto, tra cui `limit.context` annidato di OpenCode Go/Zen, `context_length` di OpenRouter, `max_model_len` di vLLM e `inputTokenLimit` di Gemini. Se è indicata solo la lunghezza massima dell’input, questa viene usata come ripiego; i limiti di output e i nomi dei modelli non determinano la capacità del contesto. In assenza di entrambe le informazioni, la finestra rimane sconosciuta.

Specificare la finestra di contesto per ogni modello, quando questo è noto. Un valore esplicito per ogni modello può sovrascrivere i metadati scoperti o completare i valori mancanti. L’editor accetta da 1 a 2.000.000 di token; si tratta di un intervallo di configurazione, non una garanzia che il fornitore supporti tale capacità. Utilizzare il limite effettivo per la propria implementazione, tenendo conto delle configurazioni del server e dei limiti propri del modello stesso.

## Campionamento, ragionamento e utilizzo

I valori predefiniti per canale/modello determinano i parametri di richiesta supportati dal fornitore selezionato. Il “Chat Composer” può fornire informazioni riguardo al processo di ragionamento, se disponibile. I diversi protocolli implementano il campionamento e il ragionamento in modi differenti; alcune opzioni potrebbero non essere supportate da un determinato modello. Iniziare con i valori predefiniti del fornitore, poi modificare una configurazione alla volta.

I LSM possono richiedere informazioni precise riguardo all’utilizzo dei token di streaming. Inoltre, possono utilizzare come soluzione alternativa il meccanismo di fallback, nel caso in cui il fornitore rifiuti esplicitamente tale opzione. Un endpoint che non restituisce informazioni sull’utilizzo dei token non può fornire dati precisi riguardo alla fatturazione o alle statistiche relative all’uso dei token. Per ulteriori informazioni, si veda la sezione [Memoria e contesto](context.md), dove viene spiegata la differenza tra il consumo cumulativo e la capacità attuale del sistema.

## Modificare e eliminare i canali

Una conversazione conserva il modello/Agente e la cronologia delle sue fasi di sviluppo. È necessario cambiare il modello quando si modificano gli endpoint o si verifica un problema legato al fornitore di servizi. Il rimozione di un canale in uso è vietata, per motivi legati alla sicurezza delle referenze. La cancellazione di un canale richiede ulteriori conferme: la cronologia rimane, ma gli agenti e i chats che fanno riferimento a quel canale devono selezionare un sostituto funzionante prima di proseguire con l’esecuzione della conversazione.

Le impostazioni del canale sono gestite dal server, e non rappresentano semplicemente delle configurazioni predefinite per il browser. Le credenziali non vengono restituite attraverso le normali risposte fornite dal catalog dei canali. È necessario proteggere il directory di stato del controller e i backup, poiché questi contengono informazioni sensibili legate alle credenziali.

## Lista di controllo per la connessione

1. Verificare che il controller riesca a raggiungere l’host dell’API, e che il protocollo TLS funzioni correttamente.
2. Confermare il percorso di base, il protocollo, le credenziali e l’identificativo esatto del modello.
3. Ripristina il processo di scoperta, oppure inserisci manualmente un modello già noto.
4. Inviate un breve messaggio di testo semplice, poi provate a utilizzare uno strumento per effettuare una piccola operazione.
5. Verifica i dettagli degli errori relativi allo stato HTTP, al timeout o alle opzioni non supportate. Non ripetere mai gli tentativi di autenticazione con credenziali non valide.

Per informazioni riguardo al gestione dei limiti di larghezza di banda, delle interruzioni del flusso di dati e degli errori di autorizzazione, consultare la sezione [Amministrazione e risoluzione dei problemi](administration.md).
