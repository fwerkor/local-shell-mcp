<!-- i18n-source-sha256: 01cf883cb71925e93fabc21d32315ef8c869ee2ea548e54a0347e2f6b730a327 -->
<!-- Machine-assisted translation; English source is authoritative. -->
# Quick Start per il Chat tramite WebUI

Lo spazio di lavoro web unificato LSM integra il sistema di chat basato sull’intelligenza artificiale, i progetti, gli agenti e le pagine operative del controller. Questo spazio di lavoro è gestito dal controller Python, che utilizza la sua autenticazione e la base di dati SQLite per il funzionamento del sistema. Non è necessario un server di chat separato. I client esterni come [ChatGPT](chatgpt-connector.md) e [Gemini](gemini-spark.md) continuano ad essere supportati.

## 1. Avviare il Controller

Seguite le istruzioni. [Installazione rapida](quickstart.md) Per il tipo di esecuzione che preferite… Assicuratevi che la WebUI sia abilitata e che venga utilizzato uno storage persistente. I valori predefiniti sono i seguenti:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

Dopo aver esportato l’ambiente di servizio, è necessario avviare il controller.

```sh
local-shell-mcp --mode mcp
```

Per il lancio in modalità singola, è necessario utilizzare l’esecutabile scaricato. Il controller installato funge da interfaccia per il frontend compilato; lo strumento per la compilazione del codice JavaScript è necessario soltanto per le build a partire dal codice sorgente. Per ulteriori informazioni, consultare [le istruzioni per la build del WebUI](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

## 2. Aprire l’area di lavoro nel browser

È possibile accedere all’indirizzo `http://127.0.0.1:8765/ui` dal host del controller, oppure utilizzando l’URL HTTPS configurato, che termina con `/ui`. È necessario effettuare l’accesso utilizzando l’autenticazione LSM configurata per quella distribuzione. Per l’accesso remoto, è necessario utilizzare il protocollo HTTPS autenticato. Le pagine di chat e di controllo condividono lo stesso origine.

## 3. Aggiungere un canale di modello

Apri il menu di selezione dei modelli e la funzione di gestione dei canali. Aggiungi un canale API oppure connetti un account supportato. Per utilizzare un endpoint compatibile con OpenAI, inserisci il nome del canale, seleziona “Chat Completions”, inserisci l’URL base dell’API e le credenziali necessarie. Puoi anche scegliere manualmente un modello da utilizzare. Salva la configurazione e seleziona il modello desiderato.

Per un servizio di inferenza locale, è necessario utilizzare un indirizzo raggiungibile dal Controller, e non soltanto dal proprio browser. Ad esempio, `http://127.0.0.1:8080/v1` è un indirizzo appropriato, se il servizio di inferenza è configurato per ascoltare su quel indirizzo all’interno del namespace di rete del Controller. Per informazioni sui protocolli, sull’autorizzazione degli account, sulla scoperta dei modelli e sui limiti legati al contesto, si veda [Channels and models](../chat/channels.md).

## 4. Eseguire una prima attività

Inizia una conversazione e fai una domanda semplice per verificare la connettività del modello. Successivamente, prova a utilizzare uno strumento di tipo “leggero” per l’accesso ai dati.

```text
Elenca i file presenti nella radice dello spazio di lavoro del controller.
Dimmi quale macchina hai ispezionato e fornisci un riassunto dei risultati ottenuti.
Non modificare i file, né eseguire alcun tipo di operazione di scrittura sui file stessi.
```

Verifica il risultato effettivo dell’utilizzo dello strumento. Se uno strumento non è disponibile, controlla le impostazioni relative agli strumenti presenti nel chat, le configurazioni dell’agente e i permessi della macchina. Utilizza un agente salvato per le task ripetitive, e configura chiaramente il suo accesso. Vedi [Strumenti e permessi](../chat/permissions.md).

![Chat tramite WebUI, con una conversazione di dimostrazione](../assets/chat/chat-workspace.png)

Le immagini presenti in questa guida e nelle pagine seguenti sono state scattate in un ambiente isolato, utilizzando un modello di dimostrazione. Le immagini non contengono credenziali o informazioni riguardanti l’utilizzo del sistema in contesti reali. I nomi dei componenti presenti nell’interfaccia utente in lingua inglese potrebbero differire da quelli presenti nella lingua selezionata.

## 5. Esplorare l’area di lavoro

| Area | Per cosa si può utilizzare? |
|---|---|
| Chat e progetti | Iniziare e cercare i chat, organizzare i progetti, utilizzare le etichette e i marcatori di messaggi. |
| Agents | Modelli, istruzioni e configurazioni degli strumenti riutilizzabili. |
| Memoria e abilità | Gestione del know-how e delle istruzioni riutilizzabili. |
| Chat programmati in anticipo. | Eseguire l’agente salvato con un prompt ricorrente. |
| File e terminali | Ispezia o esegui interventi sulle ambienti di tipo “Controller” e “Worker”. |
| Desktop | Controllo e gestione delle sessioni GUI remote supportate. |
| Sessioni, lavori e audit | Verifica delle attività svolte, dei progressi nell’esecuzione dei compiti e delle operazioni effettuate dai tool utilizzati. |
| Macchine e componenti esterni del sistema MCP | Gestisci i lavoratori e i server MCP annidati. |

L’insieme delle funzionalità disponibili dipende dalla configurazione dell’ambiente, dagli account utilizzati e dalle capacità offerte dal sistema. Chiudere il browser non annulla automaticamente la generazione dei dati da parte del server; è necessario utilizzare il comando “stop” quando si desidera interrompere le operazioni in corso.

## Passaggi successivi…

Per ulteriori informazioni sul flusso di lavoro completo, consultare la [Guida alla WebUI Chat](../chat/index.md). Per quanto riguarda la configurazione, il backup e la risoluzione degli errori, si può fare riferimento alla sezione [Amministrazione e risoluzione dei problemi](../chat/administration.md).
