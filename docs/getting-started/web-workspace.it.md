<!-- i18n-source-sha256: 474398c2065f510156f7fba24967ca8f6600b586ffb1e002416b7a10dc34c3dc -->
# Spazio di lavoro Web unificato

L'**area di lavoro web LSM unificata** è il modo consigliato per utilizzare local-shell-mcp quotidianamente. Combina la chat AI, la cronologia del progetto e il piano di controllo LSM in un'unica interfaccia reattiva, basata su un frontend LibreChat modificato e venduto. Puoi comunque connettere client MCP esterni come [ChatGPT](chatgpt-connector.md) o [Gemini](gemini-spark.md).

Lo spazio di lavoro è **auto-ospitato e installabile facoltativamente**: è un servizio Web separato, non parte dell'immagine minima del Controller, dell'eseguibile autonomo o del bundle Worker remoto. Le distribuzioni solo controller mantengono l'interfaccia utente del browser originale e OpenTUI.

## Cosa c'è nell'area di lavoro?

| Zona | Cosa puoi fare |
|---|---|
| Chat e progetti | Scegli un modello configurato, crea conversazioni, organizza progetti, trova le chat passate e archivia le conversazioni. La cronologia rimane sul server. |
| Panoramica del controllore | Visualizza lo stato, l'attività recente e le macchine connesse. |
| File | Sfoglia e gestisci file locali o remoti. |
| Terminali | Lavora con terminali persistenti sul Controller o sui Worker. |
| Desktop | Ispeziona e controlla le sessioni della GUI remota. |
| Sessioni | Ispeziona le attività LSM durevoli e il loro ciclo di vita. |
| Telecomandi | Connetti e amministra i lavoratori in uscita. |
| Controllo | Ispezionare l'attività dello strumento originato dal modello. |
| MCP nidificato | Registra, modifica, abilita, disabilita, aggiorna e rimuovi server MCP esterni dietro LSM. |

I percorsi del Controller sono `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` e `/control/audit`. La chat si apre su `/c/new`. Il gestore MCP LSM controlla il **registro MCP nidificato di LSM**; non crea un secondo registro in LibreChat.

## Distribuisci lo stack di chat opzionale

1. [Install and start an LSM Controller](quickstart.md) con OAuth, uno spazio di lavoro opportunamente isolato e archiviazione persistente dello stato `file` o `redis`. Installa Docker Compose e clona il repository sull'host che esegue lo stack web.
2. Fornisci **due origini HTTPS sullo stesso sito**, ad esempio `https://lsm.example.org` per Controller e `https://chat.example.org` per l'area di lavoro. Il servizio di chat non è esposto direttamente su una rete non attendibile.
3. Genera un segreto del bridge con `openssl rand -hex 32`. Configura queste variabili di ambiente sul **servizio Controller**, utilizzando quel segreto, quindi riavvialo:

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. Nel checkout del repository, configura lo stack web opzionale. Utilizza un file di ambiente privato o esporta i valori mostrati di seguito; generare segreti unici e forti e non impegnarli:

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. Esegui il rendering della configurazione privata, quindi crea e avvia lo stack di chat distribuito separatamente:

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

Quando si utilizza la distribuzione root Docker Compose, le variabili Controller riportate sopra appartengono alla root `.env` e vengono inoltrate al contenitore. I valori del servizio chat possono essere forniti tramite esportazioni di shell o un file di ambiente privato. Il contenitore Controller deve essere raggiungibile dal contenitore chat all'indirizzo `http://local-shell-mcp:8765` sulla rete Docker denominata. Porta il proxy inverso `127.0.0.1:3080` all'origine HTTPS della chat, preserva l'host esterno e segui [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) nel repository. Lo stack web esegue Node.js, MongoDB, Meilisearch e SearXNG; **non** sono inclusi nei Lavoratori. Questa distribuzione separata non viene avviata da un semplice `docker compose up -d` nella root del repository.

## Accedi e usa la chat

1. Apri `https://lsm.example.org/ui`, autenticati utilizzando il login **LSM Controller** e segui il trasferimento una tantum nell'area di lavoro web. Non crei un secondo account utente LibreChat.
2. Configurare un provider LLM disponibile o un endpoint modello per il servizio chat. L'area di lavoro fornisce l'interfaccia di chat e il tool bridge; **non include un modello o crediti API**.
3. Crea una conversazione. Gli strumenti di ricerca Web e LSM sono abilitati per impostazione predefinita, soggetti alle autorizzazioni del Controller. Utilizza i controlli **Web**, **LSM**, **MCP esterno** e **Memoria** per conversazione in base alle necessità.
4. Inizia con una richiesta di sola lettura: "Controlla lo stato del controller ed elenca la radice dell'area di lavoro. Non modificare i file. "
5. Passare a **File**, **Terminali**, **Desktop**, **Sessioni**, **Remoti** o **Audit** per ispezione e controllo diretti.

I caricamenti di chat (fino a 32 MiB) vengono archiviati nell'area di lavoro del Controller e i relativi percorsi assoluti vengono forniti al modello. I caricamenti nel browser non concedono autorizzazioni aggiuntive per i file. Le chiamate agli strumenti rivolti al modello passano attraverso l'autorizzazione LSM, l'audit e il router del lavoratore remoto.

## MCP esterno, sicurezza e dati

Utilizzare la barra laterale MCP dell'area di lavoro per gestire server MCP esterni nidificati. Supporta server stdio locali e server HTTP, incluse variabili di ambiente private separate e intestazioni di richiesta. I segreti non vengono restituiti al browser. L'attivazione/disattivazione della chat **MCP esterno** consente la ricerca, l'ispezione e l'invocazione di strumenti nidificati; non garantisce il modello `mcp_manage` quando gli strumenti LSM nativi sono disabilitati. La gestione dell'interfaccia utente è protetta dalla normale autorizzazione del Controller.

I messaggi di chat, i progetti e gli archivi vengono archiviati lato server nel MongoDB dello stack web; la ricerca utilizza Meilisearch. Il Controller possiede separatamente le autorizzazioni dello strumento, le identità dei lavoratori, lo stato della sessione e l'audit. Se è necessario conservare tutta la cronologia, eseguire il backup di entrambi gli archivi dati. Il backend della chat è monoutente con il login di LSM; non esporre al pubblico le sue API interne o i suoi database.

L'interfaccia utente è un'app di primo livello, **non un iframe**. Se il servizio di chat opzionale non è configurato, `/ui` continua a servire la WebUI LSM originale. OpenTUI nativo e client esterni rimangono supportati.

## Risoluzione dei problemi

- **Il reindirizzamento rimane sull'interfaccia utente originale:** controlla `LOCAL_SHELL_MCP_LIBRECHAT_URL`, un backend di stato del controller persistente e il proxy inverso HTTPS dello stack web.
- **Accesso o trasferimento non riuscito:** verifica esattamente lo stesso segreto del bridge da 32 byte o più su entrambi i lati, che corrisponda alle origini dello stesso sito, HTTPS e agli orologi del server.
- **La chat si carica ma non può rispondere:** configura un endpoint del modello effettivo o una credenziale API e controlla i log del contenitore della chat.
- **Mancano gli strumenti MCP:** verifica gli ambiti del controller e i commutatori per conversazione; il registro del server nidificato è separato dal database MCP di LibreChat.
- **File o sessioni appaiono vuoti:** verifica che la chat raggiunga il controller e l'area di lavoro corretti e controlla i relativi log di autenticazione API.

Per dettagli sull'implementazione e aggiornamenti, vedere [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) e [human interface guide](../guides/human-interface.md).
