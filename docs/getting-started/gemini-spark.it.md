<!-- i18n-source-sha256: b7c3dfd7dc21a498f8410a88a8a52094ca0349856dfa43d267e3fe7bb273685a -->
# Connetti Gemini Spark/app personalizzate

La funzionalità **app connesse personalizzate** di Gemini (precedentemente descritta come **Spark**) consente a un utente Gemini idoneo di connettersi a un server MCP remoto. LSM può fornire l'endpoint MCP. Questa è una **connessione client alternativa** a [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) e altri client MCP; non sostituisce né distribuisce il controller LSM.

Google attualmente limita le app personalizzate agli **utenti di età pari o superiore a 18 anni negli Stati Uniti**, che hanno effettuato l'accesso con un **Account Google personale** e **Mantieni attività abilitato**. La funzionalità è disponibile in **inglese**. Le connessioni devono essere create sull'app Web Gemini, sebbene le app connesse possano essere successivamente utilizzate sui dispositivi mobili. La disponibilità e le etichette dell'interfaccia utente potrebbero cambiare; consultare lo [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

## Prima di connettersi

- Avvia un runtime LSM, ad esempio con [Docker Compose](../installation/docker.md), e verificane l'integrità.
- Esporre il proprio endpoint MCP su **HTTPS raggiungibile pubblicamente** e mantenere OAuth abilitato.
- Conosci i dettagli di autenticazione del Controller e approva solo gli ambiti di cui hai bisogno.
- Utilizzare uno spazio di lavoro o un contenitore limitato. Gemini potrà richiedere operazioni con effetti reali su file, macchine e terminali.

L'endpoint da inserire in Gemini è:

```text
https://your-public-host.example.com/mcp
```

Non inserire l'interfaccia utente web (`/ui`), l'URL di LibreChat o l'origine del sito senza `/mcp`. Le distribuzioni pubbliche non devono disabilitare l'autenticazione per aggirare gli errori di connessione.

## Connettiti in Gemelli

1. Su un computer, apri [Gemini](https://gemini.google.com/) e accedi con un account personale idoneo.
2. Apri **Impostazioni e guida → App connesse**. A seconda dell'interfaccia corrente, potrebbe trovarsi in **Intelligenza personale → App connesse**.
3. In **App personalizzate**, seleziona **Aggiungi un'app personalizzata** o utilizza il campo URL dell'app personalizzata.
4. Incolla l'URL LSM HTTPS `/mcp`, quindi scegli **Avanti**.
5. Completa il flusso di consenso e OAuth con il controller LSM. LSM supporta il rilevamento OAuth e la registrazione dinamica del client. Se Gemini richiede invece credenziali client OAuth manuali, controlla le sue opzioni avanzate e la configurazione OAuth di LSM prima di procedere.
6. In una conversazione Gemini, digita `@` e seleziona l'app personalizzata connessa per richiedere uno strumento LSM.

Inizia con: "Utilizza l'app LSM connessa per ispezionare l'ambiente ed elencare i file dell'area di lavoro. Non modificare nulla. " Controllare i risultati dello strumento e l'audit del controller prima di tentare operazioni di scrittura.

## Limiti e risoluzione dei problemi

- **Nessuna opzione per app personalizzate:** conferma l'idoneità di account, regione, età, lingua e Mantieni attività. Si tratta di una limitazione di disponibilità lato Gemini, non di un errore di configurazione LSM.
- **L'URL viene rifiutato:** utilizza un endpoint HTTPS `/mcp` raggiungibile esternamente; controlla il rilevamento OAuth e il proxy inverso.
- **OAuth non riesce:** controlla la schermata di autorizzazione LSM, la registrazione del client, l'URL di richiamata e gli ambiti concessi. Non pubblicare un endpoint MCP non autenticato.
- **Uno strumento manca o non funziona correttamente:** il supporto dello schema/strumento MCP lato client può variare. Prova una semplice chiamata di sola lettura e controlla l'audit e i log di LSM; non è garantita la piena compatibilità con ogni funzionalità del client Gemini.
- **Disconnessione:** torna a **App connesse** per disattivare, scollegare o rimuovere LSM quando non è più necessario.

[official guide](https://support.google.com/gemini/answer/17209137) di Google descrive il flusso e la disponibilità più recenti delle app personalizzate. Per un'integrazione Gemini locale basata su CLI, vedere invece [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). L'LSM [ChatGPT connector tutorial](chatgpt-connector.md) rimane disponibile in modo indipendente.
