<!-- i18n-source-sha256: f2dd1c4fffcc9783c739a12868fbcfa0023e0e3a783c8ba929f84107e3959e9a -->
# Chat ospitata (opzionale)

Hosted Chat è una chat BYOK self-hosted e un client MCP Apps integrato nell'interfaccia umana di LSM. **Non** è una modalità di sessione logica: le conversazioni hanno identità indipendenti e possono facoltativamente allegare una sessione logica LSM esistente. ChatGPT e altri client esterni continuano a funzionare con le stesse sessioni e strumenti LSM.

## Abilita

La chat ospitata è disabilitata per impostazione predefinita. Imposta:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED=true
```

Riavvia il Controller e apri la **Chat ospitata** immediatamente sotto il selettore UI Web/TUI. La funzione ha anche una voce mobile nella barra superiore. L'host della chat utilizza l'identità e gli ambiti LSM OAuth esistenti. Lo stesso controller gestisce il server MCP utilizzato dal tool loop del modello; I lavoratori non possono avviare l'esecuzione.

## Profili dei modelli

Scegli **Profili modello** per creare/modificare un profilo con un nome, un URL di base API compatibile con HTTPS OpenAI, un ID modello e una chiave API opzionale. Possono coesistere più profili e le conversazioni possono cambiare modello.

Profili, conversazioni, cronologia completa dei messaggi e risultati delle chiamate agli strumenti vengono **salvati sul server** tramite il backend dello stato LSM configurato. Il loro ambito è legato all'entità autenticata. La chiave API è crittografata con AES-GCM e non viene mai restituita dagli endpoint dell'elenco dei profili o dei dettagli del profilo. Non viene archiviato nella memoria del browser, inviato al modello come prompt o incluso nei log di controllo. L'host della chat lo passa solo all'API del modello scelto.

La prima distribuzione supportata da file crea `hosted-chat-encryption-key` nella directory dello stato con la modalità 0600. **Esegui il backup di questo file insieme ai dati dello stato. Senza di essa, le chiavi API salvate non possono essere decrittografate.** Se il controller utilizza Redis, più repliche o un altro backend di stato non file, configura una chiave URL-safe-base64 stabile e condivisa a 32 byte:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY=<base64url-encoded 32 random bytes>
```

Non ruotare questa impostazione senza migrare i profili crittografati. Non utilizzare l'archiviazione dello stato in memoria quando sono necessarie conversazioni durevoli.

Per impostazione predefinita, sono accettati solo gli endpoint del modello HTTPS con nomi host DNS; gli endpoint locali/privati ​​e HTTP vengono rifiutati per ridurre il rischio di falsificazione delle richieste lato server. Gli amministratori che ospitano deliberatamente un gateway modello privato attendibile possono attivare:

```env
LOCAL_SHELL_MCP_HOSTED_CHAT_ALLOW_PRIVATE_ENDPOINTS=true
```

Non abilitarlo su un controller multiutente non attendibile a meno che gli utenti non siano autorizzati a contattare i servizi interni.

## Conversazioni e app MCP

Crea una conversazione utilizzando un profilo modello salvato. Ogni turno inviato diventa un'attività in background di proprietà del server; la chiusura del browser non annulla l'attività. Il testo completato e le chiamate allo strumento vengono controllati in modo duraturo tra i passaggi del modello/strumento. Smetti esplicitamente di interrompere. Al riavvio del controller, le corse interrotte vengono contrassegnate come tali e possono essere continuate in un nuovo turno, ma **le chiamate allo strumento con risultato sconosciuto non vengono mai riprodotte automaticamente**.

L'intera cronologia dei messaggi della conversazione viene conservata in archivio. Al modello viene inviata contemporaneamente solo una finestra recente delimitata per controllare la dimensione del contesto. Le chiamate allo strumento vengono inviate tramite l'endpoint MCP autenticato di LSM, preservando tutte le normali autorizzazioni dello strumento e il comportamento di controllo/preflight.

Apri **Live Workspace** per eseguire il rendering della risorsa App MCP `workspace_open` esistente di LSM all'interno di una vista incorporata. L'host utilizza il bridge `@modelcontextprotocol/ext-apps` per il ciclo di vita dell'app, il rinnovo delle credenziali, le chiamate agli strumenti e le azioni da uomo a agente. Non è implementato alcun secondo file manager, terminale, controllo o interfaccia utente del lavoro.

L'allegato opzionale `session_id` consente alla Chat ospitata di utilizzare e visualizzare una sessione logica esistente; non riclassifica la Sessione né attribuisce la proprietà alla Chat ospitata. Gli identificatori di conversazione chat e gli identificatori di sessione logica sono separati.

## Confini

- Le richieste del modello utilizzano i completamenti chat compatibili con OpenAI con la chiamata dello strumento; altri protocolli del provider richiedono un adattatore.
- Le salvaguardie per turno limitano le iterazioni del modello e le chiamate agli strumenti. È possibile continuare le attività più lunghe in un nuovo turno utilizzando la cronologia durevole.
- L'eliminazione della conversazione chat è esplicita. Non viene eseguita alcuna eliminazione automatica della cronologia.
- Il Controller deve essere raggiungibile in rete dal proprio client MCP e il browser deve essere autorizzato per l'API LSM Live Workspace.
